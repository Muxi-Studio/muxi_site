#coding: utf-8
from functools import wraps
from flask import abort , g , jsonify , request
from muxiwebsite.models import Permission , User

def permission_required(permission) :
    def decorator(f) :
        @wraps(f)
        def decorated(*args,**kwargs):
            if not g.current_user.can(permission) :
                print g.current_user.role
                abort(403)
            return f(*args,**kwargs)
        return decorated
    return decorator

def login_required(f) :
    @wraps(f)
    def decorated(*args,**kwargs) :
        token = request.headers.get('token')
        if token is not None :
            g.current_user = User.verify_auth_token(token)
            return f(*args,**kwargs)
        return jsonify({"login first!"}) , 401
    return decorated



