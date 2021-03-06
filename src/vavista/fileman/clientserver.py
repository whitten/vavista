"""
    Client / Server

    The fileman interface needs to operate in client server mode.
    The API is single threaded, but I want to run from a multi-threaded
    client. Each thread can connect separately to the server
"""

import json
import struct
import socket
import select
import logging
import datetime
import time

logger = logging.getLogger(__file__)

from shared import FilemanErrorNumber, FilemanError

def json_encoder(obj):
    """
        Encoder for converting Python to JSON
    """
    if type(obj) == datetime.datetime:
        # not interested in the milliseconds
        return {'__datetime__': obj.isoformat().split('.',)[0]}
    elif type(obj) == datetime.date:
        return {'__date__': obj.isoformat()}
    else:
        raise TypeError, 'Object of type %s with value of %s is not JSON serializable' % (type(obj), repr(obj))

def json_decoder(dct):
    """
        Object decoder protocol
    """
    if '__datetime__' in dct:
        # not interested in the milliseconds
        dt = dct['__datetime__'].split(".")[0]
        dt = datetime.datetime.strptime(dt, "%Y-%m-%dT%H:%M:%S")
        return dt
    elif '__date__' in dct:
        dt = dct['__date__']
        return datetime.datetime.strptime(dt, "%Y-%m-%d")
    elif '__exception__' in dct:
        if dct["__exception__"] == "FilemanErrorNumber":
            codes = dct["codes"]
            texts = dct["texts"]
            raise FilemanErrorNumber(codes=codes, texts=texts)
        if dct["__exception__"] == "FilemanError":
            message = dct["message"]
            raise FilemanError(message)
    return dct

class FilemandClient:
    socket = None
    connected = False
    _connect_data = None

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self._reconnect()
        logger.info("FilemandClient initialised")

    def _reconnect(self):
        self.socket = clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        clientsocket.connect((self.host, self.port))
        self.connected = True
        if self._connect_data:
            self.connect(**self._connect_data)

    def _mk_request(self, request_id, handle=None, data=None):
        """
            Send a request to the server
            Wait for the response
        """
        logger.debug("request_id:[%s], handle:[%s], data:[%s]", request_id, handle, data)

        if not self.connected:
            # TODO: handles are now a mess
            self._reconnect()

        try:
            if handle == None:
                handle = ""
            else:
                handle = str(handle)
            if data == None:
                data = ""
            else:
                data = json.dumps(data, default=json_encoder)

            payload_len = len(request_id) + len(handle) + len(data) + 2

            header = struct.pack("!L", payload_len) + '%s:%s:' % (request_id, handle)
            self.socket.sendall(header)
            if data != None:
                self.socket.sendall(data)

            length_message = self.socket.recv(4)
            if len(length_message) == 0:
                raise Exception("Error, Server terminated the conversation")

            assert len(length_message) == 4, "Error too few bytes returned from read"
            length = struct.unpack("!L", length_message)[0]

            if length == 0:
                return None

            recv_len  = 0
            recv_buffer = []
            while recv_len < length:
                bufsize = length - recv_len
                if bufsize > 4096:
                    bufsize = 4096
                buffer = self.socket.recv(4096)
                recv_buffer.append(buffer)
                recv_len += len(buffer)

            # To propagate exception from the server to the client.
            # The exception name is in the __exception__ value in the dict.
            # raised by the json decoder

            if length:
                recv_buffer = ''.join(recv_buffer)
                try:
                    response = json.loads(recv_buffer, object_hook=json_decoder)
                except:
                    print recv_buffer
                    raise
                return response
        except Exception, e:
            try:
                self.socket.shutdown(1)
                self.socket.close()
            except:
                pass
            self.connected = False
            raise

    def connect(self, DUZ=None, DT=None, isProgrammer=None):
        self._connect_data = dict(DUZ=DUZ, DT=DT, isProgrammer=isProgrammer)
        return self._mk_request("connect", data = dict(DUZ=DUZ, DT=DT, isProgrammer=isProgrammer))

    def list_files(self):
        return self._mk_request("list_files")

    def get_file(self, name=None, internal=True, fieldnames=None, fieldids=None):
        return self._mk_request("get_file", data = dict(name=name, internal=internal, fieldnames=fieldnames, fieldids=fieldids))

    def dbsfile_description(self, handle):
        from shared import STRING, ROWID
        rv = []
        for row in self._mk_request("dbsfile_description", handle=handle)['description']:
            if row[1] == 'STRING':
                rv.append([row[0], STRING] + row[2:])
            elif row[1] == 'ROWID':
                rv.append([row[0], ROWID] + row[2:])
            else:
                rv.append(row)
        return rv

    def dbsfile_fm_description(self, handle):
        return self._mk_request("dbsfile_fm_description", handle=handle)

    def dbsfile_get(self, handle, rowid, asdict):
        return self._mk_request("dbsfile_get", handle=handle, data=dict(rowid=rowid, asdict=asdict))

    def dbsfile_update(self, handle, **kwargs):
        return self._mk_request("dbsfile_update", handle=handle, data=kwargs)

    def dbsfile_insert(self, handle, **kwargs):
        return self._mk_request("dbsfile_insert", handle=handle, data=kwargs)

    def dbsfile_lock(self, handle, _rowid, timeout):
        return self._mk_request("dbsfile_lock", handle=handle,
            data=dict(_rowid=_rowid, timeout=timeout))

    def dbsfile_unlock(self, handle, _rowid):
        return self._mk_request("dbsfile_unlock", handle=handle,
            data=dict(_rowid=_rowid))

    def dbsfile_delete(self, handle, _rowid, filters):
        return self._mk_request("dbsfile_delete", handle=handle,
            data=dict(filters=filters, _rowid=_rowid))

    def dbsfile_traverser(self, handle, index, from_value, to_value, ascending,
            from_rule, to_rule, raw, limit, offset, asdict, filters, order_by):
        fieldnames, rows = self._mk_request("dbsfile_traverser", handle=handle,
            data = dict(index=index, from_value=from_value, to_value=to_value, 
                ascending=ascending, from_rule=from_rule, to_rule=to_rule, 
                raw=raw, limit=limit, offset=offset, filters=filters, order_by=order_by))
        for rowid, row in rows:
            if asdict:
                row = dict(zip(fieldnames, row))
                row['_rowid'] = rowid
            yield row

    def dbsfile_query(self, handle, limit, offset, asdict, filters, order_by):
        fieldnames, rows = self._mk_request("dbsfile_query", handle=handle,
            data = dict(limit=limit, offset=offset, filters=filters, order_by=order_by))
        for rowid, row in rows:
            if asdict:
                row = dict(zip(fieldnames, row))
                if type(rowid) == list:
                    row['_rowid'] = ",".join(rowid)
                    row['_parentid'] = ",".join(rowid[:-1])
                else:
                    row['_rowid'] = rowid
            yield row

    def dbsfile_count(self, handle, limit):
        return self._mk_request("dbsfile_count", handle=handle,
            data=dict(limit=limit))

    def dbsfile_fileid(self, handle):
        return self._mk_request("dbsfile_fileid", handle=handle)

    def __del__(self):
        if self.connected:
            self.socket.shutdown(1)
            self.socket.close()

class FilemandServer:
    """
        Simple server - will receive requests from a client and serve them
    """
    dbs = None
    handles = None
    rowcount = None

    def __init__(self, socket):
        self.socket = socket
        logger.info("FilemandServer initialised")

    def __call__(self):
        """
            Process requests until the socket exits

            Request Protocol:
                4 byte network format integer
                request followed by :
                handle followed by :
                data (json encoded)
            Response
                4 byte network format integer
                data (json encoded)
        """
        self.socket.setblocking(1)
        # TODO SO_REUSEADDR
        try:
            while 1:

                try:
                    ready = select.select([self.socket], [], [], 60)
                    if not ready[0]:
                        continue
                except Exception, e:
                    continue

                length_message = self.socket.recv(4)

                if len(length_message) == 0:
                    logger.info("Zero length message received, shutting down")
                    self.socket.shutdown(1)
                    self.socket.close()
                    return

                assert len(length_message) == 4, "Error too few bytes returned from read"
                length = struct.unpack("!L", length_message)[0]
                assert length > 0, "A zero length frame was received"

                recv_buffer = []
                recv_len = 0
                while recv_len < length:
                    bufsize = length - recv_len
                    if bufsize > 4096:
                        bufsize = 4096
                    try:
                        buffer = self.socket.recv(4096)
                    except socket.error, e:
                        if e.errno != 4:
                            raise e
                        buffer = ""
                    recv_buffer.append(buffer)
                    recv_len += len(buffer)
                recv_buffer = ''.join(recv_buffer)

                # TODO: can avoid a copy here
                request_id, handle, request = recv_buffer.split(':', 2)

                if handle:
                    dbsfile = self.handles[long(handle)]
                    filename = dbsfile.ext_filename+", "
                else:
                    filename = ""
                logger.debug("request: %s(%s%s)", request_id, filename, request)

                fn = getattr(self, "cmd_" + request_id)
                assert fn, "Unknown request [%s] received" % request_id

                timeStart = time.time()
                self.rowcount = None
                try:
                    if request:
                        response = fn(handle, json.loads(request))
                    else:
                        response = fn(handle)

                    if self.rowcount != None:
                        rc = "returned %d rows, " % self.rowcount
                    else:
                        rc = ""
                    logger.debug("request: %s(%s%s) %stook %f seconds",
                        request_id, filename, request, rc, time.time() - timeStart)

                except FilemanErrorNumber, e:
                    logger.exception("request [%s], raised a FilemanErrorNumber", request_id)
                    response = {"__exception__": "FilemanErrorNumber", "codes": e.codes, "texts": e.texts}
                except FilemanError, e:
                    logger.exception("request [%s], raised a FilemanError", request_id)
                    response = {"__exception__": "FilemanError", "message": e.message()}

                if response == None:
                    while 1:
                        # I am putting this in a loop because interrupts are
                        # happening GT.M being clever.
                        try:
                            self.socket.sendall(struct.pack("!L", 0))
                        except socket.error, e:
                            if e.errno != 4:
                                raise e
                            continue
                        break
                else:
                    response = json.dumps(response, default=json_encoder)
                    length = struct.pack("!L", len(response))
                    self.socket.sendall(length)
                    self.socket.sendall(response)

        except Exception, e:
            logger.exception("Exiting due to exception")
            import pdb; pdb.post_mortem()
            self.socket.shutdown(1)
            self.socket.close()

    ## These are the actual handlers.
        
    def cmd_connect(self, handle, request):
        """
            Handle a connection request
            Must be called before anything else.

            I don't want to connect to the M engine in the main server, only the child.
            Therefore, the fileman import must be here.
        """
        from vavista.fileman.dbs import DBS
        self.dbs = DBS(**request)
        self.handles = {}
        return ""

    def cmd_list_files(self, handle=None, request=None):
        """
            Return the list of files supported on this server.
        """
        return list(self.dbs.list_files())

    def cmd_get_file(self, handle, request):
        dbsfile = self.dbs.get_file(request['name'], internal=request['internal'], fieldnames=request['fieldnames'], fieldids=request['fieldids'])
        handle = id(dbsfile)
        self.handles[handle] = dbsfile
        return {'handle': str(handle)}

    def cmd_dbsfile_fm_description(self, handle, request=None):
        dbsfile = self.handles[long(handle)]
        return dbsfile.fm_description

    def cmd_dbsfile_description(self, handle, request=None):
        from shared import STRING, ROWID
        dbsfile = self.handles[long(handle)]
        rv = []
        for row in dbsfile.description:
            if row[1] == STRING:
                rv.append((row[0], 'STRING') + row[2:])
            elif row[1] == ROWID:
                rv.append((row[0], 'ROWID') + row[2:])
            else:
                rv.append((row[0], str(row[1])) + row[2:])
        return {'description': rv}

    def cmd_dbsfile_get(self, handle, request):
        dbsfile = self.handles[long(handle)]
        return dbsfile.get(request['rowid'], asdict=request['asdict'])

    def cmd_dbsfile_update(self, handle, request):
        dbsfile = self.handles[long(handle)]
        return dbsfile.update(**request)

    def cmd_dbsfile_insert(self, handle, request):
        dbsfile = self.handles[long(handle)]
        return dbsfile.insert(**request)

    def cmd_dbsfile_lock(self, handle, request):
        dbsfile = self.handles[long(handle)]
        return dbsfile.lock(_rowid=request['_rowid'], timeout=request['timeout'])

    def cmd_dbsfile_unlock(self, handle, request):
        dbsfile = self.handles[long(handle)]
        return dbsfile.unlock(_rowid=request['_rowid'])

    def cmd_dbsfile_delete(self, handle, request):
        dbsfile = self.handles[long(handle)]
        return list(dbsfile.delete(_rowid=request['_rowid'], filters=request['filters']))

    # I want to pass in:
    # order by
    # filters
    def cmd_dbsfile_traverser(self, handle, request):
        dbsfile = self.handles[long(handle)]
        rv = []
        limit = request['limit']
        cursor = dbsfile.traverser(index=request['index'], from_value=request['from_value'],
                to_value=request['to_value'], ascending=request['ascending'],
                from_rule=request['from_rule'], to_rule=request['to_rule'], raw=request['raw'],
                offset=request['offset'], filters=request['filters'], order_by=request['order_by'])
        for i, row in enumerate(cursor):
            rv.append([cursor.rowid, row])
            if limit and i >= limit-1:
                break
        self.rowcount = len(rv)
        return (dbsfile.fieldnames(), rv)

    def cmd_dbsfile_count(self, handle, request):
        dbsfile = self.handles[long(handle)]
        limit = request['limit']
        return dbsfile.count(limit = limit)

    # I want to pass in:
    # order by
    # filters
    def cmd_dbsfile_query(self, handle, request):
        dbsfile = self.handles[long(handle)]
        cursor = dbsfile.query(limit=request['limit'], offset=request['offset'], filters=request['filters'], order_by=request['order_by'])
        rv = list(cursor)
        self.rowcount = len(rv)
        return (dbsfile.fieldnames(), rv)

    def cmd_dbsfile_fileid(self, handle, request=None):
        dbsfile = self.handles[long(handle)]
        return dbsfile.fileid
