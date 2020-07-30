import time,os,sched,random,threading,traceback,datetime
import re,base64
from colors import *

import requests as r
from times import *

import markdown

def convert_markdown(s):
    return markdown.markdown(s)

from aql_defaults import *

def init_directory(d):
    try:
        os.mkdir(d)
    except FileExistsError as e:
        print_err('directory {} already exists.'.format(d), e)
    else:
        print_info('directory {} created.'.format(d))

init_directory('./static/')
init_directory('./static/upload/')

from flask_cors import CORS

from flask import Flask, session
from flask import render_template, request, send_from_directory, make_response
# from flask_gzip import Gzip

def get_secret():
    fn = 'secret.bin'
    if os.path.exists(fn):
        f = open(fn, 'rb');r = f.read();f.close()
    else:
        r = os.urandom(32)
        f = open(fn, 'wb');f.write(r);f.close()
    return r

app = Flask(__name__, static_url_path='')
app.secret_key = get_secret()
CORS(app)
# gzip = Gzip(app,minimum_size=0)

def route(r):
    def rr(f):
        app.add_url_rule(r, str(random.random()), f)
    return rr

def route_static(frompath, topath):
    @route('/'+frompath+'/<path:path>')
    def _(path): return send_from_directory(topath, path)

route_static('static', 'static')
route_static('images', 'templates/images')
route_static('css', 'templates/css')
route_static('js', 'templates/js')

aqlc.create_index('threads',
    type='persistent', fields=['t_u','t_c'], unique=False, sparse=False)
aqlc.create_index('threads',
    type='persistent', fields=['cid','t_u','t_c'], unique=False, sparse=False)
aqlc.create_index('threads',
    type='persistent', fields=['uid','t_u','t_c'], unique=False, sparse=False)

aqlc.create_index('posts',
    type='persistent', fields=['tid','t_c'], unique=False, sparse=False)
aqlc.create_index('posts',
    type='persistent', fields=['uid','t_c'], unique=False, sparse=False)

aqlc.create_index('categories',
    type='persistent', fields=['cid'], unique=True, sparse=False)

aqlc.create_index('users',
    type='persistent', fields=['t_c','t_u'], unique=False, sparse=False)
aqlc.create_index('users',
    type='persistent', fields=['t_u','t_c'], unique=False, sparse=False)
aqlc.create_index('users',
    type='persistent', fields=['uid'], unique=True, sparse=False)
aqlc.create_index('users',
    type='persistent', fields=['name'], unique=False, sparse=False)

aqlc.create_index('invitations',
    type='persistent', fields=['key','active'], unique=True, sparse=False)

is_integer = lambda i:isinstance(i, int)
class Paginator:
    def __init__(self,):
        dfs = {}
        dfs['pagenumber'] = 1
        dfs['pagesize'] = 30
        dfs['order']='desc'
        dfs['sortby']='t_u'

        self.thread_list_defaults = dfs

        dfs = dfs.copy()
        dfs['sortby']='t_c'

        self.user_thread_list_defaults = dfs

        dfs = dfs.copy()
        dfs['order'] = 'asc'
        dfs['sortby']='t_c'
        dfs['pagesize'] = 50

        self.post_list_defaults = dfs

        dfs = dfs.copy()
        dfs['order']='desc'
        self.user_post_list_defaults = dfs

        dfs = dfs.copy()
        dfs['pagesize'] = 50
        dfs['sortby'] = 'uid'
        self.user_list_defaults = dfs

    def get_user_list(self,
        sortby='uid',
        order='desc',
        pagesize=50,
        pagenumber=1,
        path=''):

        assert sortby in ['t_c','uid'] # future can have more.
        # sortby = 't_c'
        assert order in ['desc', 'asc']

        pagenumber = max(1, pagenumber)

        start = (pagenumber-1)*pagesize
        count = pagesize

        mode = 'user'

        querystring_complex = '''
        for u in users
        sort u.{sortby} {order}
        limit {start},{count}

        let stat = {{
            nthreads:length(for t in threads filter t.uid==u.uid return t),
            nposts:length(for p in posts filter p.uid==u.uid return p),
        }}

        return merge(u, stat)
        '''.format(sortby=sortby, order=order,
        start=start, count=count,)

        querystring_simple = 'return length({})'.format(querystring_complex)

        count = aql(querystring_simple, silent=True)[0]
        userlist = aql(querystring_complex, silent=True)

        pagination_obj = self.get_pagination_obj(count, pagenumber, pagesize, order, path, sortby, mode=mode)

        for u in userlist:
            userfill(u)
            # u['profile_string'] = u['name']

        return userlist, pagination_obj

    def get_post_list(self,
        by='thread',
        tid=0,
        uid=0,

        # sortby='t_c',
        order='desc',
        pagesize=50,
        pagenumber=1,

        path=''):

        assert by in ['thread', 'user']
        assert is_integer(tid)
        assert is_integer(uid)

        # assert sortby in ['t_c']
        sortby = 't_c'
        assert order in ['desc', 'asc']

        pagenumber = max(1, pagenumber)

        start = (pagenumber-1)*pagesize
        count = pagesize

        if by=='thread':
            filter = 'filter i.tid == {}'.format(tid)
            mode='post'
        else: # filter by user
            filter = 'filter i.uid == {}'.format(uid)
            mode='user_post'

        querystring_complex = '''
        for i in posts
        {filter}

        let u = (for u in users filter u.uid==i.uid return u)[0]

        sort i.{sortby} {order}
        limit {start},{count}
        return merge(i, {{user:u}})
        '''.format(
            sortby=sortby,order=order,start=start,count=count,filter=filter,
        )

        querystring_simple = '''
        return length(for i in posts {filter} return i)
        '''.format(filter=filter)

        count = aql(querystring_simple, silent=True)[0]
        # print('done',time.time()-ts);ts=time.time()

        postlist = aql(querystring_complex, silent=True)
        # print('done',time.time()-ts);ts=time.time()

        # uncomment if you want floor number in final output.
        # for idx, p in enumerate(postlist):
        #     p['floor_num'] = idx + start + 1

        pagination_obj = self.get_pagination_obj(count, pagenumber, pagesize, order, path, sortby, mode=mode)

        return postlist, pagination_obj

    def get_thread_list(self,
        by='category',
        category='all',
        uid=0,
        sortby='t_u',
        order='desc',
        pagesize=50,
        pagenumber=1,
        path=''):

        ts = time.time()

        assert by in ['category', 'user']
        assert category=='all' or is_integer(category)
        assert is_integer(uid)
        assert sortby in ['t_u', 't_c']
        assert order in ['desc', 'asc']

        pagenumber = max(1, pagenumber)

        start = (pagenumber-1)*pagesize
        count = pagesize

        if by=='category':
            if category=='all':
                filter = ''
            else:
                filter = 'filter i.cid == {}'.format(category)
            mode='thread'
        else: # filter by user
            filter = 'filter i.uid == {}'.format(uid)
            mode='user_thread'

        querystring_complex = '''
        for i in threads

        let u = (for u in users filter u.uid == i.uid return u)[0]
        let fin = (for p in posts filter p.tid == i.tid sort p.t_c desc limit 1 return p)[0]
        let count = length(for p in posts filter p.tid==i.tid return p)
        let ufin = (for j in users filter j.uid == fin.uid return j)[0]
        let c = (for c in categories filter c.cid==i.cid return c)[0]

        {filter}

        sort i.{sortby} {order}
        limit {start},{count}
        return merge(unset(i,'content'), {{user:u, last:fin, lastuser:ufin, cname:c.name, count:count}})
         '''.format(
                sortby = sortby,
                order = order,
                start = start,
                count = count,
                filter = filter,
        )

        querystring_simple = '''
        return length(for i in threads {filter} return i)
        '''.format(filter=filter)

        count = aql(querystring_simple, silent=True)[0]
        # print('done',time.time()-ts);ts=time.time()

        threadlist = aql(querystring_complex, silent=True)
        # print('done',time.time()-ts);ts=time.time()

        pagination_obj = self.get_pagination_obj(count, pagenumber, pagesize, order, path, sortby, mode)

        return threadlist, pagination_obj

    def get_pagination_obj(self, count, pagenumber, pagesize, order, path, sortby, mode='thread'):
        total_pages = max(1, (count-1) // pagesize +1)

        if total_pages > 1:
            slots = [pagenumber]
            for i in range(1,9):
                if len(slots)>=9:
                    break
                if pagenumber+i <= total_pages:
                    slots.append(pagenumber+i)
                if len(slots)>=9:
                    break
                if pagenumber-i >= 1:
                    slots.insert(0, pagenumber-i)

            slots[0] = 1
            slots[-1]=total_pages
        else:
            slots = []

        if mode=='thread':
            defaults = self.thread_list_defaults
        elif mode=='post':
            defaults = self.post_list_defaults
        elif mode=='user_thread':
            defaults = self.user_thread_list_defaults
        elif mode=='user_post':
            defaults = self.user_post_list_defaults
        elif mode=='user':
            defaults = self.user_list_defaults
        else:
            raise Exception('unsupported mode')

        def querystring(pagenumber, pagesize, order, sortby):
            ql = [] # query list

            if pagenumber!=defaults['pagenumber']:
                ql.append(('page', pagenumber))

            if pagesize!=defaults['pagesize']:
                ql.append(('pagesize', pagesize))

            if order!=defaults['order']:
                ql.append(('order', order))

            if sortby!=defaults['sortby']:
                ql.append(('sortby', sortby))

            qs = '&'.join(['='.join([str(j) for j in k]) for k in ql])
            if len(qs)>0:
                qs = path+'?'+qs
            else:
                qs = path

            return qs

        slots = [(i, querystring(i, pagesize, order, sortby), i==pagenumber) for i in slots]

        orders = [
            ('降序', querystring(pagenumber, pagesize, 'desc', sortby), order=='desc'),
            ('升序', querystring(pagenumber, pagesize, 'asc', sortby), order=='asc')
        ]

        sortbys = [
        ('最后回复', querystring(pagenumber, pagesize, order, 't_u'), 't_u'==sortby),
        ('发布时间', querystring(pagenumber, pagesize, order, 't_c'), 't_c'==sortby),
        ]

        sortbys2 = [
        ('UID',querystring(pagenumber, pagesize, order, 'uid'), 'uid'==sortby),
        ('注册时间', querystring(pagenumber, pagesize, order, 't_c'),'t_c'==sortby)
        ]

        button_groups = []

        if len(slots):
            button_groups.append(slots)

            if pagenumber!=1:
                button_groups.insert(0,[('上一页',querystring(pagenumber-1, pagesize, order,sortby))])

            if pagenumber!=total_pages:
                button_groups.append([('下一页',querystring(pagenumber+1, pagesize, order, sortby))])

        if count>1:
            button_groups.append(orders)

        if mode=='thread' or mode=='user_thread':
            button_groups.append(sortbys)

        if mode=='user':
            button_groups.append(sortbys2)

        return {
            # 'slots':slots,
            # 'orders':orders,
            # 'sortbys':sortbys,

            'button_groups':button_groups,

            'pagenumber':pagenumber,
            'pagesize':pagesize,
            'total_pages':total_pages,
            'total_count':count,
            'order':order,
        }

pgnt = Paginator()

def key(d, k):
    if k in d:
        return d[k]
    else:
        return None

def rai(k):
    v = key(request.args,k)
    return int(v) if v else 0

def ras(k):
    v = key(request.args,k)
    return str(v) if v else ''

site_name='2047'

def get_user(uid):
    return aql('for i in users filter i.uid==@k return i',
        k=uid, silent=True)[0]

logged_in = False
@app.before_request
def befr():
    global logged_in
    if 'uid' in session:
        logged_in = get_user(int(session['uid']))
    else:
        logged_in = False

@app.route('/')
@app.route('/c/all')
def catall():
    pagenumber = rai('page') or 1
    pagesize = rai('pagesize') or 30
    order = ras('order') or 'desc'
    sortby = ras('sortby') or 't_u'

    rpath = request.path
    # print(request.args)

    threadlist, pagination = pgnt.get_thread_list(
        by='category', category='all', sortby=sortby, order=order,
        pagenumber=pagenumber, pagesize=pagesize,
        path = rpath)

    return render_template('threadlist.html',
        page_title='所有分类',
        threadlist=threadlist,
        pagination=pagination,
        # threadcount=count,
        **(globals())
    )
@app.route('/u/all')
def alluser():
    pagenumber = rai('page') or 1
    pagesize = rai('pagesize') or 50
    order = ras('order') or 'desc'
    sortby = ras('sortby') or 'uid'
    rpath = request.path

    userlist, pagination = pgnt.get_user_list(
        sortby=sortby, order=order,
        pagenumber=pagenumber, pagesize=pagesize,
        path = rpath)

    return render_template('userlist.html',
        page_title='所有用户',
        # threadlist=threadlist,
        userlist = userlist,
        pagination=pagination,
        # threadcount=count,
        **(globals())
    )

@app.route('/c/<int:cid>')
def catspe(cid):
    catobj = aql('for c in categories filter c.cid==@cid return c',cid=cid, silent=True)

    if len(catobj)!=1:
        return make_response('category not exist', 404)

    catobj = catobj[0]

    pagenumber = rai('page') or 1
    pagesize = rai('pagesize') or 30
    order = ras('order') or 'desc'
    sortby = ras('sortby') or 't_u'

    rpath = request.path
    # print(request.args)

    threadlist, pagination = pgnt.get_thread_list(
        by='category', category=cid,
        sortby=sortby,
        order=order,
        pagenumber=pagenumber, pagesize=pagesize,
        path = rpath)

    return render_template('threadlist.html',
        page_title=catobj['name'],
        page_subheader=(catobj['brief'] or '').replace('\\',''),
        threadlist=threadlist,
        pagination=pagination,
        # threadcount=count,
        **(globals())
    )

@app.route('/u/<int:uid>/t')
def userthreads(uid):
    uobj = aql('''
    for u in users filter u.uid==@uid
    return u
    ''', uid=uid, silent=True)

    if len(uobj)!=1:
        return make_response('user not exist', 404)

    uobj = uobj[0]

    pagenumber = rai('page') or 1
    pagesize = rai('pagesize') or 30
    order = ras('order') or 'desc'
    sortby = ras('sortby') or 't_c'

    rpath = request.path
    # print(request.args)

    threadlist, pagination = pgnt.get_thread_list(
        by='user', uid=uid,
        sortby=sortby,
        order=order,
        pagenumber=pagenumber, pagesize=pagesize,
        path = rpath)

    return render_template('threadlist.html',
        # page_title=catobj['name'],
        page_title='帖子 - '+uobj['name'],
        threadlist=threadlist,
        pagination=pagination,
        # threadcount=count,
        **(globals())
    )

# thread, list of posts
@app.route('/t/<int:tid>')
def thrd(tid):
    thobj = aql('''
    for t in threads filter t.tid==@tid
    let u = (for u in users filter u.uid==t.uid return u)[0]
    return merge(t, {user:u})
    ''',tid=tid, silent=True)

    if len(thobj)!=1:
        return make_response('thread not exist', 404)

    thobj = thobj[0]

    pagenumber = rai('page') or 1
    pagesize = rai('pagesize') or 50
    order = ras('order') or 'asc'
    # sortby = ras('sortby') or 't_u'

    rpath = request.path

    postlist, pagination = pgnt.get_post_list(
        by='thread',
        tid=tid,
        # sortby=sortby,
        order=order,
        pagenumber=pagenumber, pagesize=pagesize,
        path = rpath)

    return render_template('postlist.html',
        page_title=thobj['title'],
        # threadlist=threadlist,
        postlist=postlist,
        pagination=pagination,
        t=thobj,
        # threadcount=count,
        **(globals())
    )

# list of user posts.
@app.route('/u/<int:uid>/p')
def uposts(uid):
    uobj = aql('''
    for u in users filter u.uid==@uid
    return u
    ''', uid=uid, silent=True)

    if len(uobj)!=1:
        return make_response('user not exist', 404)

    uobj = uobj[0]

    pagenumber = rai('page') or 1
    pagesize = rai('pagesize') or 50
    order = ras('order') or 'desc'
    # sortby = ras('sortby') or 't_u'

    rpath = request.path

    postlist, pagination = pgnt.get_post_list(
        # by='thread',
        by='user',
        # tid=tid,
        uid=uid,
        # sortby=sortby,
        order=order,
        pagenumber=pagenumber, pagesize=pagesize,
        path = rpath)

    return render_template('postlist.html',
        page_title='回复 - '+uobj['name'],
        # threadlist=threadlist,
        postlist=postlist,
        pagination=pagination,
        # t=thobj,
        u=uobj,
        # threadcount=count,
        **(globals())
    )

def userfill(u):
    if 't_c' not in u: # some user data are incomplete
        u['t_c'] = '1989-06-04T00:00:00'
        u['brief'] = '此用户的数据由于各种可能的原因，在github上2049bbs.xyz的备份中找不到，所以就只能像现在这样处理了'

@app.route('/u/<int:uid>')
def userpage(uid):
    uobj = aql('''
    for u in users filter u.uid==@uid
    return u
    ''', uid=uid, silent=True)

    if len(uobj)!=1:
        return make_response('user not exist', 404)

    uobj = uobj[0]
    u = uobj

    userfill(u)

    stats = aql('''return {
            nthreads:length(for t in threads filter t.uid==@uid return t),
            nposts:length(for p in posts filter p.uid==@uid return p),
        }
        ''',uid=uid, silent=True)[0]

    uobj['stats']=stats
    uobj['profile_string']='''
用户名 {}

UID {}

注册时间 {}

发帖 [{}](/u/{}/t)

回复 [{}](/u/{}/p)
    '''.format(u['name'], u['uid'], format_time_datetime(u['t_c']),
        stats['nthreads'], u['uid'], stats['nposts'], u['uid']
    )

    return render_template('userpage.html',
        page_title=uobj['name'],
        u=uobj,
        **(globals())
    )

from constants import *

@app.route('/register')
def regpage():
    invitation = ras('code') or ''

    return render_template('register.html',
        invitation=invitation,
        page_title='注册',
        **(globals())
    )

@app.route('/login')
def loginpage():
    username = ras('username') or ''

    return render_template('login.html',
        username=username,
        page_title='登录',
        **(globals())
    )
# print(ptf('2020-07-19T16:00:00'))

@route('/avatar/<int:uid>')
def _(uid):
    # first check db
    res = aql('for a in avatars filter a.uid==@uid return a', uid=uid, silent=True)
    # print(res)
    if len(res)>0:
        res = res[0]
        if 'data' in res:
            d = res['data']
            match = re.match(r'^data:(.*?);base64,(.*)$',d)
            mime,b64data = match[1],match[2]

            rawdata = base64.b64decode(b64data)

            resp = make_response(rawdata, 200)
            resp.headers['Content-Type'] = 'image/jpeg'
            resp.headers['Cache-Control']= 'max-age=1800'
            return resp

    resp = make_response(
        'no avatar obj found for uid {}'.format(uid), 307)
    resp.headers['Location'] = '/images/logo.png'
    resp.headers['Cache-Control']= 'max-age=1800'
    return resp

from api import api_registry
@app.route('/api', methods=['GET', 'POST'])
def apir():
    global logged_in

    def e(s): return make_response({'error':s}, 500)

    if request.method not in ['GET','POST']:
        return e('support GET and POST only')

    if request.content_length:
        if request.content_length > 1024*1024*3: # 3MB limit
            return e('request too large')

    j = request.get_json(silent=False)

    if j is None:
        if request.method=='POST':
            return e('empty body for post')
        else: # GET
            if 'action' not in request.args:
                return e('action not specified in url params')
            else:
                j = {}
                for k in request.args:
                    j[k] = request.args[k]
    else:
        if 'action' not in j:
            return e('action not specified in json')

    # print(j)
    action = j['action']
    j['logged_in'] = logged_in
    if action in api_registry:
        if action != 'ping':
            print_up(j)
        try:
            answer = api_registry[action](j)
        except Exception as ex:
            traceback.print_exc()
            errstr = ex.__class__.__name__+'/{}'.format(str(ex))
            print_err('Exception in api "{}":'.format(action), errstr)
            return e(errstr)
        else:
            if action != 'ping':
                print_down(answer)
            if 'setuid' in answer:
                session['uid'] = answer['setuid']
            if 'logout' in answer:
                del session['uid']
                
            return answer
    else:
        return e('action function not registered')

app.run(host='0.0.0.0', port='5000', debug=True)
