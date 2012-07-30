#
# Copyright (C) 2007-2012 by Johan De Taeye, frePPLe bvba
#
# This library is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero
# General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

# file : $URL$
# revision : $LastChangedRevision$  $LastChangedBy$
# date : $LastChangedDate$

from django.db import connections
from django.utils.translation import ugettext_lazy as _
from django.utils.text import capfirst
from django.utils.encoding import force_unicode
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.template import RequestContext, loader
from django.conf import settings

from freppledb.input.models import Operation
from freppledb.output.models import OperationPlan
from freppledb.common.db import sql_true, python_date
from freppledb.common.report import getBuckets
from freppledb.common.report import GridReport, GridPivot, GridFieldText, GridFieldNumber, GridFieldDateTime, GridFieldBool, GridFieldInteger


class OverviewReport(GridPivot):
  '''
  A report showing the planned starts of each operation.
  '''
  template = 'output/operation.html'
  title = _('Operation report')
  basequeryset = Operation.objects.all()
  model = Operation
  rows = (
    GridFieldText('operation', title=_('operation'), key=True, field_name='name', formatter='operation', editable=False),
    GridFieldText('location', title=_('location'), key=True, field_name='location__name', formatter='location', editable=False),
    GridFieldText(None, width=100, extra='formatter:graph', editable=False),
    )
  crosses = (
    ('locked_start', {'title': _('locked starts'),}),
    ('total_start', {'title': _('total starts'),}),
    ('locked_end', {'title': _('locked ends'),}),
    ('total_end', {'title': _('total ends'),}),
    )

  @classmethod 
  def extra_context(reportclass, request, *args, **kwargs):
    if args and args[0]:
      return {
        'title': capfirst(force_unicode(Operation._meta.verbose_name) + " " + args[0]),
        'post_title': ': ' + capfirst(force_unicode(_('plan'))),
        }      
    else:
      return {}

  @staticmethod
  def query(request, basequery, bucket, startdate, enddate, sortsql='1 asc'):
    basesql, baseparams = basequery.query.get_compiler(basequery.db).as_sql(with_col_aliases=True)
    # Run the query
    cursor = connections[request.database].cursor()
    query = '''
        select x.row1, x.row2, x.col1, x.col2, x.col3,
          min(x.frozen_start), min(x.total_start),
          coalesce(sum(case o2.locked when %s then o2.quantity else 0 end),0),
          coalesce(sum(o2.quantity),0)
        from (
          select oper.name as row1,  oper.location_id as row2,
               d.bucket as col1, d.startdate as col2, d.enddate as col3,
               coalesce(sum(case o1.locked when %s then o1.quantity else 0 end),0) as frozen_start,
               coalesce(sum(o1.quantity),0) as total_start
          from (%s) oper
          -- Multiply with buckets
          cross join (
             select name as bucket, startdate, enddate
             from common_bucketdetail
             where bucket_id = '%s' and enddate > '%s' and startdate <= '%s'
             ) d
          -- Planned and frozen quantity, based on start date
          left join out_operationplan o1
          on oper.name = o1.operation
          and d.startdate <= o1.startdate
          and d.enddate > o1.startdate
          -- Grouping
          group by oper.name, oper.location_id, d.bucket, d.startdate, d.enddate
        ) x
        -- Planned and frozen quantity, based on end date
        left join out_operationplan o2
        on x.row1 = o2.operation
        and x.col2 <= o2.enddate
        and x.col3 > o2.enddate
        -- Grouping and ordering
        group by x.row1, x.row2, x.col1, x.col2, x.col3
        order by %s, x.col2
      ''' % (sql_true(),sql_true(),basesql,bucket,startdate,enddate,sortsql)
    cursor.execute(query, baseparams)

    # Convert the SQl results to python
    for row in cursor.fetchall():
      yield {
        'operation': row[0],
        'location': row[1],
        'bucket': row[2],
        'startdate': python_date(row[3]),
        'enddate': python_date(row[4]),
        'locked_start': row[5],
        'total_start': row[6],
        'locked_end': row[7],
        'total_end': row[8],
        }


class DetailReport(GridReport):
  '''
  A list report to show operationplans.
  '''
  template = 'output/operationplan.html'
  title = _("Operation detail report")
  basequeryset = OperationPlan.objects.extra(select={'operation_in': "select name from operation where out_operationplan.operation = operation.name",})
  model = OperationPlan
  frozenColumns = 0
  editable = False
  rows = (
    GridFieldInteger('id', title=_('operationplan'), key=True, editable=False),
    GridFieldText('operation', title=_('operation'), formatter='operation', editable=False),
    GridFieldNumber('quantity', title=_('quantity'), editable=False),
    GridFieldDateTime('startdate', title=_('start date'), editable=False),
    GridFieldDateTime('enddate', title=_('end date'), editable=False),
    GridFieldBool('locked', title=_('locked'), editable=False),
    GridFieldNumber('unavailable', title=_('unavailable'), editable=False),
    GridFieldInteger('owner', title=_('owner'), editable=False),
    )


@staff_member_required
def GraphData(request, entity):
  basequery = Operation.objects.filter(pk__exact=entity)
  (bucket,start,end,bucketlist) = getBuckets(request)
  total_start = []
  total_end = []
  for x in OverviewReport.query(request, basequery, bucket, start, end):
    total_start.append(x['total_start'])
    total_end.append(x['total_end'])
  context = {
    'buckets': bucketlist,
    'total_end': total_end,
    'total_start': total_start,
    'axis_nth': len(bucketlist) / 20 + 1,
    }
  return HttpResponse(
    loader.render_to_string("output/operation.xml", context, context_instance=RequestContext(request)),
    mimetype='application/xml; charset=%s' % settings.DEFAULT_CHARSET
    )
