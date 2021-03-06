from datetime import datetime
import random as random_module

from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse
from django.http import Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.template import RequestContext

from views.main import register
from wiki.models.courses import Course, CourseSemester, Professor
from wiki.models.pages import Page
from wiki.models.series import Series, SeriesBanner
from wiki.utils.constants import terms, years, exam_types
from wiki.utils.currents import current_term, current_year
from wiki.utils.decorators import show_object_detail
from wiki.utils.gitutils import NoChangesError
from wiki.utils.merge3 import Merge3
from wiki.utils.pages import page_types


@show_object_detail(Page, show_custom_404=True)
def show(request, page, **groups):
    if page is None:
        return create(request, groups['department'], groups['number'],
            groups['page_type'], (groups['term'], groups['year']))

    if not page.can_view(request.user):
        raise PermissionDenied

    return {
        'title': str(page),
        'course': page.course_sem.course,
        'page': page,
        'page_type': page_types[page.page_type],
    }


@show_object_detail(Page)
def printview(request, page):
    if not page.can_view(request.user):
        raise PermissionDenied

    return {
        'page': page,
        'page_type': page_types[page.page_type],
    }


@show_object_detail(Page)
def history(request, page):
    if not page.can_view(request.user):
        raise PermissionDenied

    repo = page.get_repo()
    commit_history = repo.get_history()

    return {
        'title': 'Page history for %s' % page,
        'course': page.course_sem.course,
        'page': page,
        'commit_history': commit_history,
    }


# View page information for a specific commit
@show_object_detail(Page, always_pass_groups=True)
def commit(request, page, **kwargs):
    if not page.can_view(request.user):
        raise PermissionDenied

    page_type_obj = page_types[page.page_type]
    repo = page.get_repo()
    commit = repo.get_commit(kwargs['hash'])
    if commit is None:
        raise Http404

    return {
        'title': 'Commit information for %s' % page,
        'course': page.course_sem.course,
        'page': page,
        'commit': commit,
    }


@login_required
@show_object_detail(Page)
def edit(request, page):
    if not page.can_view(request.user):
        raise Http404

    page_type_obj = page_types[page.page_type]
    latest_commit_hash = page.get_latest_commit_hash()
    repo = page.get_repo()
    course = page.course_sem.course

    # If we're in section editing
    section = request.GET.get('section')
    if section:
        content, start, end = page.load_section_content(section)
    else:
        content = page.load_content()
        start = 0
        end = 0

    merge_conflict = False
    no_changes = False
    if request.method == 'POST':
        new_content = request.POST['content']
        # Just do save sections with the data
        username = request.user.username
        message = request.POST['message'] if request.POST['message'] else 'Minor edit'
        prev_commit_hash = request.POST['last_commit']

        # Someone edited in between the last commit and this one
        # We'll try a 3-way merge, and tell the user to review
        if prev_commit_hash != latest_commit_hash:
            current = request.POST['content'].splitlines()
            other_commit = repo.get_commit(latest_commit_hash)
            other = other_commit.get_content().splitlines()
            base_commit = repo.get_commit(prev_commit_hash)
            base = base_commit.get_content().splitlines()
            merged = Merge3(base, current, other)

            for group in merged.merge_groups():
                if 'conflict' in group:
                    merge_conflict = True

            lines = merged.merge_lines(
                start_marker="<<<<<<< Your edits",
                mid_marker="======= Changes that occurred during editing",
                end_marker=">>>>>>>")

            # Not sure why there's a carriage return everywhere but yeah
            new_content = "\r\n".join(lines)
            content = new_content

        # If there's there's there's no commits between this save 
        # and the one this page thinks was the last one, or if there
        # isn't a conflict(successful merge)
        if prev_commit_hash == latest_commit_hash or not merge_conflict:
            try:
                hexsha = page.save_content(new_content, message, username, start=start, end=end)
            except NoChangesError:
                no_changes = True
                hexsha = None

            # Only change the metadata if the user is a moderator
            if request.user.is_staff:
                page.edit(request.POST)
                no_changes = False

            if not no_changes:
                # Add the history item
                course.add_event(page=page, user=request.user, action='edited',
                    message=message, hexsha=hexsha)

                # If the user isn't watching the course already, start watching
                user = request.user.get_profile()
                if not user.is_watching(course):
                    user.start_watching(course)

                return redirect(page.get_absolute_url())

    field_templates = page_type_obj.get_editable_fields()
    non_field_templates = ['pages/%s_data.html' % field for field in page_type_obj.editable_fields]

    return {
        'professors': Professor.objects.all(),
        'current_professor': page.professor.id if page.professor else 0,
        'no_changes': no_changes,
        'conflict': merge_conflict,
        'title': 'Editing %s' % page,
        'course': course,
        'page': page,
        # ONLY SHOW THE BELOW FOR MODERATORS (once that is implemented)
        'field_templates': field_templates if request.user.is_staff else non_field_templates,
        'page_type': page_type_obj,
        'latest_commit': latest_commit_hash,
        'content': content,
        'subject': page.subject,
        'exam_types': exam_types,
    }


@login_required
def create(request, department, number, page_type, semester=None):
    course = get_object_or_404(Course, department=department.upper(), number=int(number))

    if page_type not in page_types:
        raise Http404

    form_action = reverse('pages_create', args=[department, number, page_type])
    page_type_obj = page_types[page_type]
    data = {
        'form_action': form_action,
        'professors': Professor.objects.all(),
        'title': 'Create a page (%s)' % course,
        'course': course,
        'page_type': page_type_obj,
        'terms': terms,
        'field_templates': page_type_obj.get_uneditable_fields() + page_type_obj.get_editable_fields(),
        'years': years,
        'page_type_url': page_type_obj.get_url(course), # can't call it on page_type_obj directly
        'current_term': current_term,
        'current_year': current_year,
        'exam_types': exam_types,
        'current_exam_type': exam_types[0], # default
        'edit_mode': False,
        'course_series': course.series_set.all(),
    }

    if semester is not None:
        data['current_term'] = semester[0]
        data['current_year'] = int(semester[1])
        data['does_not_exist'] = True

    if request.method == 'POST':
        errors = page_type_obj.find_errors(request.POST)
        kwargs = page_type_obj.get_kwargs(request.POST)
        course_sem, created = CourseSemester.objects.get_or_create(term=request.POST['term'], year=request.POST['year'], course=course)

        existing_page = Page.objects.filter(course_sem=course_sem,
            slug=kwargs['slug'])
        if errors or existing_page: # it returns None only if nothing is wrong
            data['errors'] = errors
            if existing_page:
                data['errors'].append('A <a href="%s">page</a> with the same '
                    'slug already exists! Perhaps you meant to edit that one '
                    'instead? Alternatively, you could change the details '
                    'for this page.' % existing_page[0].get_absolute_url())

            # Keep the posted data
            data['current_term'] = request.POST['term']
            try:
                data['current_year'] = int(request.POST['year'])
            except ValueError:
                pass # defaults to the current year
            data['current_exam_type'] = request.POST['exam_type'] if 'exam_type' in request.POST else ''
            data['subject'] = request.POST['subject'] if 'subject' in request.POST else ''

            data['content'] = request.POST['content']
            data['message'] = request.POST['message']
            try:
                data['current_professor'] = int(request.POST['professor_id'])
            except (ValueError, KeyError):
                pass

            return render(request, 'pages/create.html', data)
        else:
            commit_message = request.POST['message'] if request.POST['message'] else 'Minor edit'
            # The title and subject are generated by the PageType object, in kwargs
            new_page = Page.objects.create(course_sem=course_sem, page_type=page_type, maintainer=request.user, **kwargs)
            username = request.user.username
            email = request.user.email
            hexsha = new_page.save_content(request.POST['content'], commit_message, username)

            # Add the history item - should be done automatically one day
            course.add_event(page=new_page, user=request.user, action='created',
                message=commit_message, hexsha=hexsha)
            data['page'] = new_page

            # If the user isn't watching the course already, start watching
            user = request.user.get_profile()
            if not user.is_watching(course):
                user.start_watching(course)

            # Create the SeriesPage if a series is specified, at the end of the
            # series. Temporary and very hacky solution, pls fix later
            series_id = request.POST.get('series_id')
            if series_id:
                series_query = Series.objects.filter(pk=series_id,
                                                     course=course)
                if series_query.exists():
                    series = series_query[0]
                    next_position = series.get_next_position()
                    series.seriespage_set.create(page=new_page, series=series,
                                                 position=next_position)

            return redirect(new_page.get_absolute_url())

    return render(request, 'pages/create.html', data)


def random(request):
    pages = Page.objects.all()
    random_page = random_module.choice(pages)

    while not random_page.can_view(request.user):
        random_page = random_module.choice(pages)

    return redirect(random_page.get_absolute_url())
