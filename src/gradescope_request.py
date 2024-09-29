from dataclasses import dataclass
import logging as log
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests
from enum import Enum
from datetime import datetime


class Constants:
    BASE_URL = 'https://www.gradescope.com'
    LOGIN_URL = f'{BASE_URL}/login'
    GRADEBOOK = 'https://www.gradescope.com/courses/{course_id}/gradebook.json?user_id={member_id}'
    PAST_SUBMISSIONS = '.json?content=react&only_keys%5B%5D=past_submissions'


@dataclass
class Course:
    '''Represents a course in Gradescope.'''
    course_id: int
    url: str
    term: str
    short_name: str
    full_name: str

    def get_url(self) -> str:
        '''Returns the full URL of the course.'''
        return urljoin(Constants.BASE_URL, self.url)


@dataclass
class Assignment:
    '''Represents an assignment in Gradescope.'''
    assignment_id: int
    ready_for_submission: bool
    url: str
    title: str
    late_submission_warning: bool
    submission_status: str
    released_time: str
    due_time: str

    def get_url(self) -> str:
        '''Returns the full URL of the assignment.'''
        return urljoin(Constants.BASE_URL, self.url)

    def get_grades_url(self) -> str:
        '''Returns the URL to download the grades for the assignment.'''
        return urljoin(Constants.BASE_URL, self.url + '/scores.csv')


@dataclass
class Submission:
    '''Represents a submission in Gradescope.'''
    course_id: int
    assignment_id: int
    member_id: int
    submission_id: int
    created_at: str
    score: int
    url: str

    def get_url(self) -> str:
        '''Returns the full URL of the submission.'''
        return urljoin(Constants.BASE_URL, self.url)

    def get_file_url(self) -> str:
        '''Returns the URL to download the submission file.'''
        return urljoin(Constants.BASE_URL, self.url + '.zip')


class GradescopeError(Exception):
    def __init__(self, msg: str):
        self.msg = msg

    def __str__(self):
        return self.msg


class LoginError(GradescopeError):
    def __init__(self, msg: str = 'Login failed, please check username and password.'):
        super().__init__(msg)


class NotLoggedInError(GradescopeError):
    def __init__(self, msg: str = 'Not logged in.'):
        super().__init__(msg)


class ResponseError(GradescopeError):
    def __init__(self, msg: str):
        super().__init__(msg)


class Gradescope:
    '''
    A minimal Gradescope wrapper.
    TODO: Documentation
    '''

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password
        self.session = requests.session()

        log.basicConfig(level=log.INFO)

        is_logged = self.login()
        if is_logged:
            log.info('[Info] Login successful.')
        else:
            log.warning('[Warning] Login failed.')

    def login(self) -> bool:
        if self.username is None or self.password is None:
            raise TypeError('The username or password cannot be None.')

        response = self.session.get(Constants.BASE_URL)
        self._response_check(response)
        soup = BeautifulSoup(response.text, 'html.parser')
        token_input = soup.find('input', attrs={'name': 'authenticity_token'})

        if token_input:
            authenticity_token = token_input.get('value')

        data = {
            'authenticity_token': authenticity_token,
            'session[email]': self.username,
            'session[password]': self.password,
            'session[remember_me]': 0,
            'commit': 'Log In',
            'session[remember_me_sso]': 0,
        }
        response = self.session.post(Constants.LOGIN_URL, data=data)
        self._response_check(response)

        if 'account' in response.url:
            self.logged_in = True
            return True
        elif 'login' in response.url:
            self.logged_in = False
            return False
        else:
            self.logged_in = False
            raise LoginError('Unknown return URL.')

    def get_courses(self):
        if not self.logged_in:
            raise NotLoggedInError

        response = self.session.get(Constants.BASE_URL)
        self._response_check(response)
        soup = BeautifulSoup(response.text, 'html.parser')

        courses = list()
        current_heading = soup.find('h1', string="Your Courses")
        if current_heading:
            course_lists = current_heading.find_next_sibling(
                'div', class_='courseList')
            for term in course_lists.find_all(class_='courseList--term'):
                term_name = term.get_text(strip=True)
                courses_container = term.find_next_sibling(
                    class_='courseList--coursesForTerm')
                if courses_container:
                    for course in courses_container.find_all(class_='courseBox'):
                        if course.name == 'a':
                            courses.append(
                                Course(
                                    course_id=self._parse_int(
                                        course.get('href', '').split('/')[-1]),
                                    url=course.get('href', None),
                                    term=term_name,
                                    short_name=course.find(
                                        class_='courseBox--shortname').get_text(strip=True),
                                    full_name=course.find(
                                        class_='courseBox--name').get_text(strip=True)
                                )
                            )
        else:
            raise ResponseError(f'Cannot find heading "Your Courses"')
        log.info(f'[Info] Found {len(courses)} courses.')
        return courses

    def get_term_courses(self):
        courses = self.get_courses()
        term_courses = []
        current_month = datetime.now().month
        current_year = datetime.now().year

        if 2 <= current_month <= 6:
            season = "Spring"
        elif 9 <= current_month <= 12:
            season = "Fall"
        else:
            season = "Summer"
        # TODO: Need checking

        term_courses = [course for course in courses if course.term == f"{
            season} {current_year}"]
        log.info(f'[Info] Found {len(term_courses)
                                 } courses for the current term.')
        return term_courses

    def get_assignments(self, course):
        if not self.logged_in:
            raise NotLoggedInError

        response = self.session.get(course.get_url())
        self._response_check(response)
        soup = BeautifulSoup(response.text, 'html.parser')
        assignments_data = soup.find(
            'table', {'id': 'assignments-student-table'})

        assignments = []
        for row in assignments_data.find('tbody').find_all('tr'):
            assignment = {}
            button = row.find('button', {'class': 'js-submitAssignment'})
            assignment['assignment_id'] = int(button['data-assignment-id'])
            assignment['ready_for_submission'] = button['data-ready-for-submission'] == 'true'
            assignment['url'] = button['data-post-url']
            assignment['title'] = button['data-assignment-title']
            assignment['late_submission_warning'] = button['data-show-late-submission-warning'] == 'true'
            assignment['submission_status'] = row.find('td', {'class': 'submissionStatus'}).find('div', {'class': 'submissionStatus--text'}).text.strip()
            assignment['released_time'] = row.find('time', {'class': 'submissionTimeChart--releaseDate'})['datetime']
            assignment['due_time'] = row.find('time', {'class': 'submissionTimeChart--dueDate'})['datetime']
            assignments.append(assignment)
        return assignments

    def get_past_submissions(self, course, assignment):
        pass

    def get_assignment_grades(self, course, assignment):
        pass

    def download_file(self, url, path):
        pass

    def _response_check(self, response: requests.Response) -> bool:
        '''
        Checks the response status code and raises an error if it's not 200.

        Args:
            response (requests.Response): The response object.

        Returns:
            bool: True if the status code is 200.

        Raises:
            ResponseError: If the status code is not 200.
        '''
        if response.status_code == 200:
            return True
        else:
            raise ResponseError(f'Failed to fetch the webpage. Status code: {
                                response.status_code}. URL: {response.url}')

    def _parse_int(self, text: str) -> int:
        '''
        Parses an integer from a given text.

        Args:
            text (str): The text containing the integer.

        Returns:
            int: The parsed integer.
        '''
        return int(''.join(re.findall(r'\d', text)))
