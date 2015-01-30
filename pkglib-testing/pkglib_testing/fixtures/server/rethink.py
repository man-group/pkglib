import socket

import pytest
import rethinkdb
from rethinkdb.errors import RqlRuntimeError
import uuid
import logging

from pkglib_testing import CONFIG

from .base import TestServer
from ..util import requires_config

log_format = ("%(levelname)-5s %(asctime)s.%(msecs)03d " +
              "module:%(module)s %(message)s")
logging.basicConfig(format=log_format, datefmt='%Y-%m-%d %H:%M:%S',
                    level=logging.INFO)
log = logging.getLogger(__name__)


def _rethink_server(request):
    """ This does the actual work - there are several versions of this used
        with different scopes.
    """
    test_server = RethinkDBServer()
    request.addfinalizer(lambda p=test_server: p.teardown())
    test_server.start()
    return test_server


@requires_config(['rethink_executable'])
@pytest.fixture(scope='function')
def rethink_server(request):
    """ Function-scoped RethinkDB server in a local thread.
    """
    return _rethink_server(request)


@requires_config(['rethink_executable'])
@pytest.fixture(scope='session')
def rethink_server_sess(request):
    """ Same as rethink_server fixture, scoped as session instead.
    """
    return _rethink_server(request)


@pytest.yield_fixture(scope="function")
def rethink_unique_db(rethink_server_sess):
    """ Starts up a session-scoped server, and returns a connection to
        a unique database for the life of a single test, and drops it after
    """
    dbid = uuid.uuid4().hex
    conn = rethink_server_sess.conn
    rethinkdb.db_create(dbid).run(conn)
    conn.use(dbid)
    yield conn
    rethinkdb.db_drop(dbid).run(conn)


@pytest.yield_fixture(scope="module")
def rethink_module_db(rethink_server_sess):
    """ Starts up a session-scoped server, and returns a connection to
        a unique database for all the tests in one module.
        Drops the database after module tests are complete.
    """
    dbid = uuid.uuid4().hex
    conn = rethink_server_sess.conn
    log.info("Making database called {}".format(dbid))
    rethinkdb.db_create(dbid).run(conn)
    conn.use(dbid)
    yield conn
    log.info("Dropping database")
    rethinkdb.db_drop(dbid).run(conn)


@pytest.fixture(scope="module")
def rethink_make_tables(rethink_tables, rethink_module_db):
    """ Module-scoped fixture to build RethinkDB tables.
        Requires a module or session-scoped fixture to be defined
        somewhere that tells us what those tables are, as a list
        of (tablename, primary_key_name) tuples.

        Example::

            @pytest.fixture(scope='module')
            def rethink_tables():
                return [('staff', 'staff_id'),
                        ('department', 'dept_id')
                        ]
    """
    log.debug("Building RethinkDB tables: {}" .format(rethink_tables))
    conn = rethink_module_db
    for table_name, primary_key in rethink_tables:
        try:
            (rethinkdb.db(conn.db)
             .table_create(table_name, primary_key=primary_key,)
             .run(conn)
             )
            log.info('Made table "{}" with key "{}"'
                     .format(table_name, primary_key))
        except RqlRuntimeError as err:
            log.error('Table "{}" not made: {}'
                      .format(table_name, err.message))


@pytest.yield_fixture(scope="function")
def rethink_empty_db(rethink_tables, rethink_module_db, rethink_make_tables):
    """ Given a module scoped database, we need to empty all the tables
        for each test to ensure no interaction between test table content.

        This is a useful approach, because of the long time taken to
        create a new RethinkDB table, compared to the time to empty one.
    """
    tables_to_emptied = (table[0] for table in rethink_tables)
    conn = rethink_module_db

    for table_name in tables_to_emptied:
        rethinkdb.db(conn.db).table(table_name).delete().run(conn)
        log.debug('Emptied "{}" before test'.format(table_name))
    yield conn


class RethinkDBServer(TestServer):
    random_port = True

    def __init__(self, **kwargs):
        super(RethinkDBServer, self).__init__(**kwargs)
        self.cluster_port = self.get_port()
        self.http_port = self.get_port()
        self.db = None

    @property
    def run_cmd(self):
        return [CONFIG.rethink_executable,
                '--directory', self.workspace / 'db',
                '--bind', socket.gethostbyname(self.hostname),
                '--driver-port', str(self.port),
                '--http-port', str(self.http_port),
                '--cluster-port', str(self.cluster_port),
        ]

    def check_server_up(self):
        """Test connection to the server."""
        log.info("Connecting to RethinkDB at {}:{}".format(
            self.hostname, self.port))
        try:
            self.conn = rethinkdb.connect(host=self.hostname,
                                          port=self.port, db='test')
            return True
        except rethinkdb.RqlDriverError as err:
            log.warn(err)
        return False
