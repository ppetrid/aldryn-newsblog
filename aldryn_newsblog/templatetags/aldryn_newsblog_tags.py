import re
from django.template import Library

register = Library()

@register.simple_tag(takes_context=True)
def build_page_url(context, page):
    param = (context['view'].config.pagination_link_type == 'param')
    inner = context['view'].inner_page_view
    path = context['request'].path

    if page == 1:
        return re.sub('/page/(\d+)/$', '/', path) if inner \
            else path

    # the url to a page >= 2 was requested
    if inner:
        # for sure we use URL-type pagination because we render
        # an inner page view
        return re.sub('/page/(\d+)/$', '/page/%s/' % page, path)

    url = '%s/?page=%s' if param else '%s/page/%s/'
    return url % (re.sub('/$', '', path), page)
