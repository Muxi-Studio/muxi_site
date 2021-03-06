# coding: utf-8

"""
models.py

    数据库模型
"""

from . import db, login_manager, app
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer
from random import seed
from flask import current_app, request, url_for
from flask_login import UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import AnonymousUserMixin
from datetime import datetime
import sys
import bleach
from markdown import markdown
import hashlib
import base64
import pickle


# secondary table
# 多对多关系
UBLike = db.Table(
    # 用户和博客的关联表
    "user_blog_likes",
    db.Column('user_id', db.Integer, db.ForeignKey('users.id')),
    db.Column('blog_id', db.Integer, db.ForeignKey('blogs.id'))
)


BTMap = db.Table(
    # 博客与标签的关联表
    "blog_tag_maps",
    db.Column('blog_id', db.Integer, db.ForeignKey('blogs.id',ondelete='cascade')),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id',ondelete='cascade'))
)


class Permission:
    """
    用户权限定义(base 16)
    """
    COMMENT = 0x02  # 评论权限
    WRITE_ARTICLES = 0x04  # 写文章权限
    MODERATE_COMMENTS = 0x08  # 修改评论权限
    ADMINISTER = 0x80  # 管理员权限，修改所有


class Role(db.Model):
    """
    用户角色定义
    """
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True)
    default = db.Column(db.Boolean, default=False, index=True)
    permissions = db.Column(db.Integer)
    users = db.relationship('User', backref='role', lazy='dynamic')

    @staticmethod
    def insert_roles():
        """
        插入角色
            1.User: 可以评论、写文章 true(默认)
            2.Moderator: 可以评论写文章,删除评论
            3.Administer: 管理员(想干什么干什么)
        需调用此方法，创建角色
        """
        roles = {
            # | 表示按位或操作,base 16进行运算
            'User': (Permission.COMMENT |
                     Permission.WRITE_ARTICLES, True),
            'Moderator': (Permission.COMMENT |
                          Permission.WRITE_ARTICLES |
                          Permission.MODERATE_COMMENTS, False),
            'Administrator': (0xff, False)
        }
        for r in roles:
            role = Role.query.filter_by(name=r).first()
            if role is None:
                role = Role(name=r)
            role.permissions = roles[r][0]
            role.default = roles[r][1]
            db.session.add(role)  # 添加进数据库
        db.session.commit()  # 提交

    def __repr__(self):
        """该类的'官方'表示方法"""
        return '<Role %r>' % self.name

class Book(db.Model):
    """图书类"""
    __searchable__ = ['name', 'tag', 'summary', 'bid']
    __tablename__ = "books"
    id = db.Column(db.Integer, primary_key = True)
    url = db.Column(db.String(164))
    bid = db.Column(db.Text)
    name = db.Column(db.Text)
    author = db.Column(db.Text)
    tag = db.Column(db.String(164))
    summary = db.Column(db.Text)
    image = db.Column(db.String(164))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    status = db.Column(db.Boolean)
    start = db.Column(db.String(164))
    end = db.Column(db.String(164))

    def __repr__(self):
        return "%r :The instance of class Book" % self.name


class User(db.Model, UserMixin):
    """用户类"""
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key = True) # user id (auto generate)

    email = db.Column(db.String(164)) # email address
    birthday = db.Column(db.String(164)) # user's birthday
    hometown = db.Column(db.String(164)) # hometown address and coordinates
    group = db.Column(db.String(164)) # group info (be, fe, design, android, product)
    timejoin = db.Column(db.String(164)) # time of joining muxi
    timeleft = db.Column(db.String(164)) # time of leaving muxi
    username = db.Column(db.String(164), unique=True)
    password_hash = db.Column(db.String(164))

    left = db.Column(db.Boolean)

    info = db.Column(db.Text) # talk about yourself
    # url of your avatar (suggestion: upload to qiniu or imugur)
    # tool: Drag (https://github.com/bHps2016/Drag)
    avatar_url = db.Column(db.Text)

    # blog and social networks' urls
    personal_blog = db.Column(db.Text)
    github = db.Column(db.Text)
    flickr = db.Column(db.Text)
    weibo = db.Column(db.Text)
    zhihu = db.Column(db.Text)

    book = db.relationship('Book', backref="user", lazy="dynamic")
    share = db.relationship('Share', backref="user", lazy="dynamic")
    comments = db.relationship('Comment', backref='author', lazy='dynamic')
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'))
    # 用户发布的博客
    blogs = db.relationship('Blog', backref='author', lazy='dynamic')

    def __init__(self, **kwargs):
        """用户角色实现"""
        super(User, self).__init__(**kwargs)
        if self.role is None:
            self.role = Role.query.filter_by(default=True).first()

    def can(self, permissions):
        """判断用户的权限"""
        return self.role is not None and (self.role.permissions & permissions) == permissions

    def is_admin(self):
        """判断当前用户是否是管理员"""
        return self.role_id == 2

    @property
    def password(self):
        """将密码方法设为User类的属性"""
        raise AttributeError('密码原始值保密, 无法保存!')

    @password.setter
    def password(self, password):
        """设置密码散列值"""
        password = base64.b64decode(password)
        self.password_hash = generate_password_hash(password)

    def verify_password(self, password):
        """验证密码散列值"""
        return check_password_hash(self.password_hash, password)

    def generate_auth_token(self):
        """generate a token"""
        s = Serializer(current_app.config['SECRET_KEY'],expires_in = 604800 )
        # token 七天过期
        return s.dumps({'id': self.id})

    @staticmethod
    def verify_auth_token(token):
        """verify the user with token"""
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token)
        except:
            return None
        # get id
        return User.query.get_or_404(data['id'])

    def to_json(self):
        json_user = {
            'id' : self.id,
            'username' : self.username,
            'email' : self.email
            # 'share' : null  # => 待share api编写完成
        }

    @staticmethod
    def from_json(json_user):
        u = User(
            username = json_user.get('username'),
            password = json_user.get('password'),
            email = json_user.get('email')
        )
        return u

    def __repr__(self):
        return "%r :The instance of class User" % self.username


class AnonymousUser(AnonymousUserMixin):
    """
	匿名用户类
	谁叫你匿名，什么权限都没有
	"""

    def can(self, permissions):
        return False

    def is_admin(self):
        return False


login_manager.anonymous_user = AnonymousUser


@login_manager.user_loader
def load_user(user_id):
    """flask-login要求实现的用户加载回调函数
		依据用户的unicode字符串的id加载用户"""
    return User.query.get(int(user_id))


class Share(db.Model):
    """分享类"""
    __tablename__ = "shares"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text)
    share = db.Column(db.Text)
    tag = db.Column(db.Text)
    content = db.Column(db.Text)  # 存取markdown渲染以后的内容
    read_num = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.now)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    comment = db.relationship('Comment', backref='shares', lazy='dynamic')
    comment_num = db.Column(db.Integer,default=0)

    @staticmethod
    def generate_fake(count=10):
        # 生成虚拟数据
        from random import seed, randint
        import forgery_py

        seed()
        user_count = User.query.count()
        for i in range(count):
            u = User.query.offset(randint(0, user_count - 1)).first()
            p = Share(
                title=forgery_py.lorem_ipsum.title(randint(1, 5)),
                share=forgery_py.lorem_ipsum.sentences(randint(1, 5)),
                timestamp=forgery_py.date.date(True),
                author_id=u.id
            )
            db.session.add(p)
            db.session.commit()

    def to_json(self):
        author = User.query.filter_by(id=self.author_id).first()
        if not author:
            username = ""
        else:
            username = author.username
        if  self.tag :
            tag = self.tag
        else :
            tag = ""
        try :
            share = pickle.loads(self.share)
        except :
            share = self.share
            print "share can not load in api"
        try :
            title  = pickle.loads(self.title)
        except  :
            title = self.title
            print "titie can not load in  api"
        #comment_num = len(Comment.query.filter_by(share_id=self.id).all())
        json_share = {
            'id' : self.id,
            'tag' : tag ,
            'title' : title,
            'share' : share,
            'date' : self.timestamp,
            'read_num' : self.read_num,
            'username' : username,
            'comment_num' : self.comment_num ,
            'comment' : url_for('shares.view_share2', id=self.id),
            'avatar' : author.avatar_url ,
            'user_id' : author.id ,
        }
        return json_share

    def to_json3(self):
        author = User.query.filter_by(id=self.author_id).first()
        if not author:
            username = ""
        else:
            username = author.username
        try :
            share = pickle.loads(self.share)
        except  :
            share = self.share
            print "share can not load in api"
        try :
            title  = pickle.loads(self.title)
        except  :
            title = self.title
            print "title can not load in api"
        if  self.tag :
            tag = self.tag
        else  :
            tag = ""
       # comment_num = len(Comment.query.filter_by(share_id=self.id).all())
        json_share = {
            'id' : self.id,
            'title' : title ,
            'share' : share,
            'date' : self.timestamp,
            'tag' : tag ,
            'comment_num' : self.comment_num ,
            'read_num' : self.read_num,
            'username' : username,
            'comment' : url_for('shares.view_share2', id=self.id),
            'avatar' : author.avatar_url ,
        }
        return json_share


    def to_json2(self):
        try :
            share = pickle.loads(self.share)
        except  :
            share = self.share
            print "share can not load in api"
        try :
            title  = pickle.loads(self.title)
        except  :
            title = self.title
            print "title can not load in api"
        json_share = {
            'id' : self.id,
            'title' : title ,
            'share' : share ,
            'date' : self.timestamp,
        }
        return json_share

    @staticmethod
    def from_json(json_share):
        share = Share(
            title = json_share.get('title'),
            share = json_share.get('share'),
            author_id = current_user.id
        )
        return share

    def __repr__(self):
        return "%r is instance of class Share" % self.title


class Comment(db.Model):
    """评论类"""
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    comment = db.Column(db.Text)
    count = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.now)
    share_id = db.Column(db.Integer, db.ForeignKey('shares.id'))
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    blog_id = db.Column(db.Integer, db.ForeignKey('blogs.id'))
    author_name = db.Column(db.String(30))

    def to_json(self):
        try :
            comment = pickle.loads(self.comment)
        except  :
            comment = self.comment
            print "comment can not load  in api"
        json_comment = {
            'date' : self.timestamp,
            'comment' : comment,
            'username' : User.query.filter_by(id=self.author_id).first().username ,
            'avatar' : User.query.filter_by(id=self.author_id).first().avatar_url ,
        }
        return json_comment

    def __repr__(self):
        return "<the instance of model Comment>"



class Blog(db.Model):
    """博客类"""
    __tablename__ = 'blogs'
    id = db.Column(db.Integer, primary_key = True)
    name = db.Column(db.String(164))
    # body 直接存markdown，在服务器端渲染
    title = db.Column(db.Text)
    body = db.Column(db.Text)
    summary = db.Column(db.Text)
    img_url = db.Column(db.String(164))
    timestamp = db.Column(db.DateTime, index=True, default=datetime.now)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    # 文章分类: 一篇文章对应一个分类
    type_id = db.Column(db.Integer)
    comments = db.relationship('Comment', backref='blog', lazy='dynamic')
    likes_number = db.Column(db.Integer, default=0)
    comment_number = db.Column(db.Integer, default=0)
    # 喜欢这篇博客的用户列表
    # this is a relationship so we call User
    liked_users = db.relationship(
        "User",
        secondary=UBLike,
        backref=db.backref("liked_blogs", lazy="dynamic"),
        lazy="dynamic",
    )
    # 博客对应的标签
    tags = db.relationship(
        "Tag",
        secondary=BTMap,
        backref=db.backref("blogs", lazy='dynamic',cascade='all'),
        passive_deletes = True ,
        single_parent = True ,
        cascade="all, delete-orphan" ,
        lazy="dynamic"
    )

    @property
    def index(self):
        """
        以年月的形式对文章进行归档
        ex: 15年12月
        :return:
        """
        return str(self.timestamp)[:4]+"年"+\
            str(self.timestamp)[5:7]+"月"

    @property
    def liked(self):
        """
        属性函数, 判断当前用户是否点赞这门课
        :return:
        """
        if current_user in self.liked_users:
            return True
        else:
            return False

    @staticmethod
    def generate_fake(count=100):
        # 生成虚拟数据
        from random import randint
        import forgery_py

        seed()
        user_count = User.query.count()
        for i in range(count):
            u = User.query.offset(randint(0, user_count - 1)).first()
            b = Blog(
                body = forgery_py.lorem_ipsum.sentences(randint(1, 5)),
                timestamp =forgery_py.date.date(True),
                author = u
            )
            db.session.add(b)
            db.session.commit()

    def to_json(self):
        author = User.query.filter_by(id=self.author_id).first()
        comment_num = len(Comment.query.filter_by(blog_id=self.id).all())
        if not author:
            username = ""
        else:
            username = author.username
        #这里是有很多种类型的错误，不捕获了，反正也只是反序列化 　
        try :
            body = pickle.loads(self.body)
        except  :
            body = self.body
            print "blog can not load in api"
        try :
            title = pickle.loads(self.title)
        except  :
            title = self.title
            print "blog 's title can not load in api"
        try :
            summary = pickle.loads(self.summary)
        except :
            summary = self.summary

        if len(summary) == 0 :
            summary = body[:100]

        json_blog = {
            'id' : self.id,
            'title' : title,
            'body' : body,
            'date' : self.timestamp,
            'username' : username,
            'comment' : url_for('blogs.view_comment2', id=self.id),
            'comment_num' : comment_num ,
            'avatar' : author.avatar_url ,
            'summary' : summary ,
            'type' :  self.type_id ,
            'img_url' : self.img_url ,
            'tags' : [ item.value for item in self.tags ],
            'tag_num' : len(list(self.tags)) ,
	        'likes' : self.likes_number,
            'likes_users' : [ item.username for item in self.liked_users ] ,
        }
        return json_blog

    def to_json2(self) :
        date = "%d/%02d/%02d" % (self.timestamp.year, self.timestamp.month, self.timestamp.day) ,
        json_blog = {
            "date" : date ,
            "blog" : url_for('blogs.view2', id=self.id) ,
        }
        return json_blog

    def find_month(self,year,month) :
        if int(self.timestamp.year) == int(year) and int(self.timestamp.month) == int(month) :
            return True
        return False

    @staticmethod
    def on_changed_body(target, value, oldvalue, initiator):
        allowed_tags = ['a', 'abbr', 'acronym', 'b', 'blockquote', 'code',
                        'em', 'i', 'li', 'ol', 'pre', 'strong', 'ul',
                        'h1', 'h2', 'h3', 'p']
        target.body_html = bleach.linkify(bleach.clean(
            markdown(value, output_format='html'),
            tags=allowed_tags, strip=True))

db.event.listen(Blog.body, 'set', Blog.on_changed_body)


class Type(db.Model):
    """
    博客文章的分类
    ex: 前端，后台，安卓，设计...
    """
    __tablename__ = 'types'
    id = db.Column(db.Integer, primary_key=True)
    value = db.Column(db.String(64))

    def __repr__(self):
        return "<type %d>" % self.id


class Tag(db.Model):
    """
    博客文章的标签
    ex: js, css, flask...
    """
    __tablename__ = 'tags'
    id = db.Column(db.Integer, primary_key=True)
    value = db.Column(db.String(64))

    def __repr__(self):
        return "<type %d>" % self.id
