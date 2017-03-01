import argparse
import binascii
import sys
import os
import types
import re

from Crypto import Random
from hashlib import md5
from getpass import getpass

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import OperationalError, ProgrammingError, IntegrityError

from emcapi import EMCClient
from celery import Celery


celery = Celery('emcweb')
Base = declarative_base()


class Credentials(Base):
    __tablename__ = 'credentials'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    name = Column(String(255))
    password = Column(String(255))

class Users(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)


@celery.task
def test_celery(data):
    print(data)


def test_sql_connection(kwargs):
    error_str = ''
    database_uri = kwargs['SQLALCHEMY_DATABASE_URI']
    username = kwargs['account']['username']
    password = kwargs['account']['password']

    engine = create_engine(database_uri)
    session_cls = sessionmaker(bind=engine)
    sess = session_cls()
    sess._model_changes = {}

    try:
        result = sess.execute('select * from alembic_version')
    except OperationalError:
        error_str = 'Database connection refused'
    except ProgrammingError:
        error_str = 'Database is not configured.'

    strings = [row[0] for row in result]
    if len(strings) < 1:
        error_str = 'Database is not configured'
    
    if error_str:
        return False, error_str
    else:
        pass
        res, error = create_credentials(username, password, sess)
        if not res:
            return False, error
        else:
            return True, ''
    return False, error_str


def create_credentials(username, password, sess):
    error_str = ''

    try:
        result = sess.execute('select * from credentials where name="{}"'.format(username))
    except:
        return False, 'Not found table credentials in database'

    if result and result.rowcount > 0:
        return False, 'EMC WEB user "{}" already exists'.format(username)

    new_user = Users()
    sess.add(new_user)
    try:
        sess.commit()
    except:
        return False, 'Error creating user'

    try:
        result = sess.execute('select max(id) AS last_id from users')
    except:
        return False, 'Not found table users in database'
   
    for row in result:
        max_id = row[0]
        break

    new_credentials = Credentials(user_id = max_id, name=username, password=md5(password.encode()).hexdigest())
    sess.add(new_credentials)
    
    try:
        sess.commit()
    except:
        return False, 'Error creating credentials "{}" already exists'.format(username)
    
    return True, ''


def test_celery_connection(kwargs):
    error_str = ''

    celery.config_from_object(kwargs)
        
    try:
        test_celery.delay()
    except:
        error_str = 'Celery transport connection refused'
    
    if error_str:
        return False, error_str
    else:
        return True, ''

def test_emc_connection(kwargs):
    emc_client = EMCClient(
                           host=kwargs['EMC_SERVER_HOST'],
                           port=kwargs['EMC_SERVER_PORT'],
                           user=kwargs['EMC_SERVER_USER'],
                           password=kwargs['EMC_SERVER_PASSWORD'],
                           protocol=kwargs['EMC_SERVER_PROTO'],
                           verify=False)

    info = emc_client.getinfo()
    if info.get('error', False):
        return False, info['error']['message']
    else:
        return True, ''


def config_flask(kwargs):
    key_pattern = re.compile(r'^#?([\w]+) ?= ?(.+)$')

    ex_file = os.path.join(os.path.dirname(__file__), '..', 'settings', 'flask.py.example')
    flask_file = os.path.join(os.path.dirname(__file__), '..', 'settings', 'flask.py')

    if not os.path.exists(ex_file):
        return False, 'Not exists file "flask.py.example"'

    old_file = open(ex_file, 'r').read().split('\n')
    new_file = []
    
    kwargs['SECRET_KEY'] = generate_secret_key(32)
    kwargs['WTF_CSRF_SECRET_KEY'] = generate_secret_key(32)

    for line in old_file: 
        match_obj = key_pattern.search(line)
        
        if match_obj and len(match_obj.groups()) == 2 \
           and kwargs.get(match_obj.group(1), False):
            line = '{0} = {1}'.format(
                    match_obj.group(1),
                    repr(kwargs.get(match_obj.group(1), '')))
        
        new_file.append(line)
    
    res, error = test_sql_connection(kwargs)
    if not res:
        return False, error

    res, error = test_celery_connection(kwargs)
    if not res:
        return False, error
    
    res, error = test_emc_connection(kwargs)
    if not res:
        return False, error

    try:
        f = open(flask_file, 'w')
        f.write('\n'.join(new_file))
        f.close()
    except:
        return False, 'Error write config file on disk'

    return True, ''

def generate_secret_key(length):
    result = binascii.hexlify(Random.get_random_bytes(length // 2))

    if result[0] == 48:
        result = b'f' + random_name[1:]

    return result.decode()