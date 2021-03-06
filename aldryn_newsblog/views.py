# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import re

from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from django.db.models import Q
from django.http import (
    Http404,
    HttpResponseRedirect,
    HttpResponsePermanentRedirect,
    HttpResponse
) 
from django.shortcuts import get_object_or_404
from django.utils import translation
from django.views.generic import ListView
from django.views.generic.detail import DetailView

from menus.utils import set_language_changer
from parler.views import TranslatableSlugMixin, ViewUrlMixin
from taggit.models import Tag

from cms.utils.conf import get_cms_setting

from aldryn_apphooks_config.mixins import AppConfigMixin
from aldryn_categories.models import Category
from aldryn_people.models import Person

from aldryn_newsblog.utils.utilities import get_valid_languages_from_request
from .cache import set_blog_page_cache, get_blog_page_cache
from .models import Article
from .utils import add_prefix_to_path


class BlogCacheMixin(object):
    def get_cached_blog_page(self):
        if get_cms_setting("PAGE_CACHE") and (
            not hasattr(self.request, 'toolbar') or (
                not self.request.toolbar.edit_mode and
                not self.request.toolbar.show_toolbar and
                not self.request.user.is_authenticated()
            )
        ):
            cache_content = get_blog_page_cache(self.request)
            if cache_content is not None:
                content, headers = cache_content
                response = HttpResponse(content)
                response._headers = headers
                return response


class TemplatePrefixMixin(object):

    def prefix_template_names(self, template_names):
        if (hasattr(self.config, 'template_prefix') and
                self.config.template_prefix):
            prefix = self.config.template_prefix
            return [
                add_prefix_to_path(template, prefix)
                for template in template_names]
        return template_names

    def get_template_names(self):
        template_names = super(TemplatePrefixMixin, self).get_template_names()
        return self.prefix_template_names(template_names)


class PaginationLinkTypeMixin(object):
    """ A mixin that handles the pagination link type preference """
    # Whether this view is a first page view (e.g. /myslug/)
    # or an inner view (e.g. /myslug/page/2/)
    inner_page_view = False

    def get(self, request, *args, **kwargs):
        if self.inner_page_view:
            # if this is an inner page and we
            # have selected a parameter-based pagination
            # a page not found error should be raised
            if self.config.pagination_link_type == 'param':
                raise Http404

            try:
                page = int(kwargs.get(self.page_kwarg))
            except:
                page = 1

            # this is an inner page view and the user
            # tries to visit the first page.
            # he should be redirected to the outer view
            if page == 1:
                return HttpResponsePermanentRedirect(
                    re.sub('/page/(\d+)/$', '/', request.path)
                )

        return super(PaginationLinkTypeMixin, self) \
                .get(request, *args, **kwargs)

    def paginate_queryset(self, queryset, page_size):
        if not self.inner_page_view:
            if self.config.pagination_link_type == 'url':
                # ensure the `page` parameter is ignored
                # and we always get the first page 
                self.page_kwarg = ''
            else:
                self.page_kwarg = 'page'

        return super(PaginationLinkTypeMixin, self) \
                .paginate_queryset(queryset, page_size)


class EditModeMixin(object):
    """
    A mixin which sets the property 'edit_mode' with the truth value for
    whether a user is logged-into the CMS and is in edit-mode.
    """
    edit_mode = False

    def dispatch(self, request, *args, **kwargs):
        self.edit_mode = (
            self.request.toolbar and self.request.toolbar.edit_mode)
        return super(EditModeMixin, self).dispatch(request, *args, **kwargs)


class PreviewModeMixin(EditModeMixin):
    """
    If content editor is logged-in, show all articles. Otherwise, only the
    published articles should be returned.
    """
    def get_queryset(self):
        qs = super(PreviewModeMixin, self).get_queryset()
        if not self.edit_mode:
            qs = qs.published()
        language = translation.get_language()
        qs = qs.active_translations(language).namespace(self.namespace)
        return qs


class AppHookCheckMixin(object):

    def dispatch(self, request, *args, **kwargs):
        self.valid_languages = get_valid_languages_from_request(
            self.namespace, request)
        return super(AppHookCheckMixin, self).dispatch(
            request, *args, **kwargs)

    def get_queryset(self):
        # filter available objects to contain only resolvable for current
        # language. IMPORTANT: after .translated - we cannot use .filter
        # on translated fields (parler/django limitation).
        # if your mixin contains filtering after super call - please place it
        # after this mixin.
        qs = super(AppHookCheckMixin, self).get_queryset()
        return qs.translated(*self.valid_languages)


class ArticleDetail(BlogCacheMixin, AppConfigMixin, AppHookCheckMixin, PreviewModeMixin,
                    TranslatableSlugMixin, TemplatePrefixMixin, DetailView):
    model = Article
    slug_field = 'slug'
    year_url_kwarg = 'year'
    month_url_kwarg = 'month'
    day_url_kwarg = 'day'
    slug_url_kwarg = 'slug'
    pk_url_kwarg = 'pk'

    def get(self, request, *args, **kwargs):
        """
        This handles non-permalinked URLs according to preferences as set in
        NewsBlogConfig.
        """
        cached_response = self.get_cached_blog_page()
        if cached_response:
            return cached_response

        if not hasattr(self, 'object'):
            self.object = self.get_object()
        set_language_changer(request, self.object.get_absolute_url)
        url = self.object.get_absolute_url()
        if (self.config.non_permalink_handling == 200 or request.path == url):
            # Continue as normal
            response = super(ArticleDetail, self).get(request, *args, **kwargs)
            # cache the response
            response.add_post_render_callback(set_blog_page_cache)
            return response

        # Check to see if the URL path matches the correct absolute_url of
        # the found object
        if self.config.non_permalink_handling == 302:
            return HttpResponseRedirect(url)
        elif self.config.non_permalink_handling == 301:
            return HttpResponsePermanentRedirect(url)
        else:
            raise Http404('This is not the canonical uri of this object.')

    def get_object(self, queryset=None):
        """
        Supports ALL of the types of permalinks that we've defined in urls.py.
        However, it does require that either the id and the slug is available
        and unique.
        """
        if queryset is None:
            queryset = self.get_queryset()

        slug = self.kwargs.get(self.slug_url_kwarg, None)
        pk = self.kwargs.get(self.pk_url_kwarg, None)

        if pk is not None:
            # Let the DetailView itself handle this one
            return DetailView.get_object(self, queryset=queryset)
        elif slug is not None:
            # Let the TranslatedSlugMixin take over
            return super(ArticleDetail, self).get_object(queryset=queryset)

        raise AttributeError('ArticleDetail view must be called with either '
                             'an object pk or a slug')

    def get_context_data(self, **kwargs):
        context = super(ArticleDetail, self).get_context_data(**kwargs)
        context['prev_article'] = self.get_prev_object(
            self.queryset, self.object)
        context['next_article'] = self.get_next_object(
            self.queryset, self.object)
        return context

    def get_prev_object(self, queryset=None, object=None):
        if queryset is None:
            queryset = self.get_queryset()
        if object is None:
            object = self.get_object(self)
        prev_objs = queryset.filter(
            publishing_date__lt=object.publishing_date
        ).order_by(
            '-publishing_date'
        )[:1]
        if prev_objs:
            return prev_objs[0]
        else:
            return None

    def get_next_object(self, queryset=None, object=None):
        if queryset is None:
            queryset = self.get_queryset()
        if object is None:
            object = self.get_object(self)
        next_objs = queryset.filter(
            publishing_date__gt=object.publishing_date
        ).order_by(
            'publishing_date'
        )[:1]
        if next_objs:
            return next_objs[0]
        else:
            return None


class ArticleListBase(AppConfigMixin, AppHookCheckMixin, TemplatePrefixMixin,
                      PreviewModeMixin, ViewUrlMixin, PaginationLinkTypeMixin,
                      ListView):
    model = Article
    show_header = False

    def get_paginate_by(self, queryset):
        if self.paginate_by is not None:
            return self.paginate_by
        else:
            try:
                return self.config.paginate_by
            except AttributeError:
                return 10  # sensible failsafe

    def get_pagination_options(self):
        # Django does not handle negative numbers well
        # when using variables.
        # So we perform the conversion here.
        if self.config:
            options = {
                'pages_start': self.config.pagination_pages_start,
                'pages_visible': self.config.pagination_pages_visible,
            }
        else:
            options = {
                'pages_start': 10,
                'pages_visible': 4,
            }

        pages_visible_negative = -options['pages_visible']
        options['pages_visible_negative'] = pages_visible_negative
        options['pages_visible_total'] = options['pages_visible'] + 1
        options['pages_visible_total_negative'] = pages_visible_negative - 1
        return options

    def get_context_data(self, **kwargs):
        context = super(ArticleListBase, self).get_context_data(**kwargs)
        context['pagination'] = self.get_pagination_options()
        return context


class ArticleListCachedMixin(BlogCacheMixin):
    def get(self, request, *args, **kwargs):
        """ Retrieved cached response. """
        cached_response = self.get_cached_blog_page()
        if cached_response:
            return cached_response

        response = super(ArticleListCachedMixin, self).get(request, *args, **kwargs)
        # do not cache param-style paginated pages
        if self.config.pagination_link_type == 'url':
            response.add_post_render_callback(set_blog_page_cache)
        return response


class ArticleList(ArticleListCachedMixin, ArticleListBase):
    """A complete list of articles."""
    show_header = True

    def get_queryset(self):
        qs = super(ArticleList, self).get_queryset()
        # exclude featured articles from queryset, to allow featured article
        # plugin on the list view page without duplicate entries in page qs.
        exclude_count = self.config.exclude_featured
        if exclude_count:
            featured_qs = Article.objects.all().filter(is_featured=True)
            if not self.edit_mode:
                featured_qs = featured_qs.published()
            exclude_featured = featured_qs[:exclude_count].values_list('pk')
            qs = qs.exclude(pk__in=exclude_featured)
        return qs


class ArticleListInnerPage(ArticleList):
    inner_page_view = True


class ArticleSearchResultsList(ArticleListBase):
    model = Article
    http_method_names = ['get', 'post', ]
    partial_name = 'aldryn_newsblog/includes/search_results.html'
    template_name = 'aldryn_newsblog/article_list.html'

    def get(self, request, *args, **kwargs):
        self.query = request.GET.get('q')
        self.max_articles = request.GET.get('max_articles', 0)
        self.edit_mode = (request.toolbar and request.toolbar.edit_mode)
        return super(ArticleSearchResultsList, self).get(request)

    def get_paginate_by(self, queryset):
        """
        If a max_articles was set (by a plugin), use that figure, else,
        paginate by the app_config's settings.
        """
        return self.max_articles or super(
            ArticleSearchResultsList, self).get_paginate_by(self.get_queryset())

    def get_queryset(self):
        qs = super(ArticleSearchResultsList, self).get_queryset()
        if not self.edit_mode:
            qs = qs.published()
        if self.query:
            return qs.filter(
                Q(translations__title__icontains=self.query) |
                Q(translations__lead_in__icontains=self.query) |
                Q(translations__search_data__icontains=self.query)
            ).distinct()
        else:
            return qs.none()

    def get_context_data(self, **kwargs):
        cxt = super(ArticleSearchResultsList, self).get_context_data(**kwargs)
        cxt['query'] = self.query
        return cxt

    def get_template_names(self):
        if self.request.is_ajax:
            template_names = [self.partial_name]
        else:
            template_names = [self.template_name]
        return self.prefix_template_names(template_names)


class ArticleSearchResultsListInnerPage(ArticleSearchResultsList):
    inner_page_view = True


class AuthorArticleList(ArticleListBase):
    """A list of articles written by a specific author."""
    def get_queryset(self):
        # Note: each Article.author is Person instance with guaranteed
        # presence of unique slug field, which allows to use it in URLs
        return super(AuthorArticleList, self).get_queryset().filter(
            author=self.author
        )

    def get(self, request, author, **kwargs):
        language = translation.get_language_from_request(
            request, check_path=True)
        self.author = Person.objects.language(language).active_translations(
            language, slug=author).first()
        if not self.author:
            raise Http404('Author not found')
        return super(AuthorArticleList, self).get(request, **kwargs)

    def get_context_data(self, **kwargs):
        kwargs['newsblog_author'] = self.author
        return super(AuthorArticleList, self).get_context_data(**kwargs)


class AuthorArticleListInnerPage(AuthorArticleList):
    inner_page_view = True


class CategoryArticleList(ArticleListCachedMixin, ArticleListBase):
    """A list of articles filtered by categories."""
    def get_queryset(self):
        return super(CategoryArticleList, self).get_queryset().filter(
            categories=self.category
        )

    def get(self, request, category, **kwargs):
        self.category = get_object_or_404(
            Category, translations__slug=category)
        return super(CategoryArticleList, self).get(request, **kwargs)

    def get_context_data(self, **kwargs):
        kwargs['newsblog_category'] = self.category
        ctx = super(CategoryArticleList, self).get_context_data(**kwargs)
        ctx['newsblog_category'] = self.category
        return ctx


class CategoryArticleListInnerPage(CategoryArticleList):
    inner_page_view = True


class TagArticleList(ArticleListCachedMixin, ArticleListBase):
    """A list of articles filtered by tags."""
    def get_queryset(self):
        return super(TagArticleList, self).get_queryset().filter(
            tags=self.tag
        )

    def get(self, request, tag, **kwargs):
        self.tag = get_object_or_404(Tag, slug=tag)
        return super(TagArticleList, self).get(request, **kwargs)

    def get_context_data(self, **kwargs):
        kwargs['newsblog_tag'] = self.tag
        return super(TagArticleList, self).get_context_data(**kwargs)


class TagArticleListInnerPage(TagArticleList):
    inner_page_view = True


class DateRangeArticleList(ArticleListCachedMixin, ArticleListBase):
    """A list of articles for a specific date range"""
    def get_queryset(self):
        return super(DateRangeArticleList, self).get_queryset().filter(
            publishing_date__gte=self.date_from,
            publishing_date__lt=self.date_to
        )

    def _daterange_from_kwargs(self, kwargs):
        raise NotImplemented('Subclasses of DateRangeArticleList need to'
                             'implement `_daterange_from_kwargs`.')

    def get(self, request, **kwargs):
        self.date_from, self.date_to = self._daterange_from_kwargs(kwargs)
        return super(DateRangeArticleList, self).get(request, **kwargs)

    def get_context_data(self, **kwargs):
        kwargs['newsblog_day'] = (
            int(self.kwargs.get('day')) if 'day' in self.kwargs else None)
        kwargs['newsblog_month'] = (
            int(self.kwargs.get('month')) if 'month' in self.kwargs else None)
        kwargs['newsblog_year'] = (
            int(self.kwargs.get('year')) if 'year' in self.kwargs else None)
        if kwargs['newsblog_year']:
            kwargs['newsblog_archive_date'] = date(
                kwargs['newsblog_year'],
                kwargs['newsblog_month'] or 1,
                kwargs['newsblog_day'] or 1)
        return super(DateRangeArticleList, self).get_context_data(**kwargs)


class YearArticleList(DateRangeArticleList):
    def _daterange_from_kwargs(self, kwargs):
        date_from = datetime(int(kwargs['year']), 1, 1)
        date_to = date_from + relativedelta(years=1)
        return date_from, date_to


class YearArticleListInnerPage(YearArticleList):
    inner_page_view = True


class MonthArticleList(DateRangeArticleList):
    def _daterange_from_kwargs(self, kwargs):
        date_from = datetime(int(kwargs['year']), int(kwargs['month']), 1)
        date_to = date_from + relativedelta(months=1)
        return date_from, date_to


class MonthArticleListInnerPage(MonthArticleList):
    inner_page_view = True


class DayArticleList(DateRangeArticleList):
    def _daterange_from_kwargs(self, kwargs):
        date_from = datetime(
            int(kwargs['year']), int(kwargs['month']), int(kwargs['day']))
        date_to = date_from + relativedelta(days=1)
        return date_from, date_to


class DayArticleListInnerPage(DayArticleList):
    inner_page_view = True
