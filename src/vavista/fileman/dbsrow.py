"""
    The DBSRow maps to a single Fileman record.

    The data retrieval, insert, update and delete logic belongs here.
"""

from vavista import M
from shared import FilemanError
from transaction import transaction_manager as transaction

class FilemanValidationError(FilemanError):
    filename, row, fieldid, value, error_code, error_msg = None, None, None, None, None, None
    err, help = None, None
    def __init__(self, **kwargs):
        for k,v in kwargs.items():
            setattr(self, k, v)
    def __str__(self):
        return """file [%s], row = [%s], fieldid = [%s], value = [%s], error_code = [%s], error_msg = [%s] help = %s""" \
            % (self.filename, self.row, self.fieldid, self.value, self.error_code, self.error_msg,
            self.help)

class FilemanLockFailed(FilemanError):
    filename, row, timeout = None, None, None
    def __init__(self, **kwargs):
        for k,v in kwargs.items():
            setattr(self, k, v)
    def __str__(self):
        return """file [%s], row = [%s], timeout = [%s]""" \
            % (self.filename, self.row, self.timeout)

class DBSRow(object):
    """
        This is the key to the whole implementation.  This object maps to a single row
        in the Fileman global. You use it to retrieve fields from that row and to update
        that row. This class has to take care of conversions between Python and M, and
        to ensure that the integrity of the M data store is not violated.

        Access either by id:   row["0.1"]
        or label:              row["name"]

        TODO: lots
        What about the other values, e.g. subfiles, wp files - do they come across.
    """
    _changed = False
    _changed_fields = []
    _locked = False
    _dbsfile = None
    _dd = None
    _rowid = None
    _fields = None
    _fieldids = None
    _stored_data = None
    _row_tmpid = None
    _row_fdaid = None

    def __init__(self, dbsfile, dd, rowid, fieldids):
        self._dbsfile = dbsfile
        self._dd = dd
        self._rowid = rowid

        if fieldids:
            self._fields = dict([(k,v) for (k,v) in dd.fields.items() if v.fieldid in fieldids])
            self._fieldids = fieldids
        else:
            self._fields = dd.fields
            self._fieldids = [v.fieldid for (k,v) in dd.fields.items()]

        # Lazy evaluation
        self._row_tmpid = "row%s" % id(self)
        self._stored_data = None
        if rowid is None:
            g = M.Globals()
            self._stored_data = dict(g[self._row_tmpid][self._dd.fileid][self._iens])

    def _before_value_change(self, fieldid, global_var, value):
        """
            This should be invoked before the application modifies a variable
            in this row. This function should validate the value, apply any
            formatting rules required and notify the transactional machinary 
            that this object is changed.
        """
        # At this stage, I just want to validate against the data 
        # dictionary. At write time, the data will be fully validated.

        g = M.Globals()
        g["ERR"].kill()

        # Validates single field against the data dictionary
        s0, = M.proc("CHK^DIE", self._dd.fileid, fieldid, "H",
            value, M.INOUT(""), "ERR")

        err = g["ERR"]

        # s0 should contain ^ for error, internal value for valid data
        if s0 == "^":
            error_code = err['DIERR'][1].value
            error_msg = '\n'.join([v for k,v in err['DIERR'][1]['TEXT'].items()])
            help_msg = [v for k,v in err['DIHELP'].items()]

            # Invalid data - get the error from the ERR structure
            raise FilemanValidationError(filename = self._dd.filename, row = self._rowid, 
                    fieldid = fieldid, value = value, error_code = error_code, error_msg = error_msg,
                    err = err, help=help_msg)

        # If err exists, then some form of programming error
        if err.exists():
            raise FilemanError("""DBSRow._set_value(): file [%s], fileid = [%s], rowid = [%s], fieldid = [%s], value = [%s]"""
                % (self._dd.filename, self._dd.fileid, self._rowid, fieldid, value), str(err))

        if not self._changed:
            self._lock()
            transaction.join(self)

        if fieldid not in self._changed_fields:
            self._changed_fields.append(fieldid)

        return value

    def _lock(self, timeout=5):
        """
            Lock a global (path to a row).
            This functionality is here so that transaction management
            can remove locks on a commit, abort
        """
        if self._locked: return

        if self._rowid: # nothing to lock

            g = M.Globals()
            g_path = self._dd.m_closed_form(self._rowid)

            # Set the timeout
            g["DILOCKTM"].value = timeout

            # use DILF^LOCK function to perform the lock
            M.proc("LOCK^DILF", g_path)

            # result is returned in $T
            rv, = M.mexec("set l0=$T", M.INOUT(0))
            if rv != 1:
                raise FilemanLockFailed(filename=self._dd.filename, row=self._rowid, timeout=timeout)
            self._locked = 1

    def _unlock(self):
        # Locking is done via an M level routine on the record global
        if self._locked:
            g_path = self._dd.m_closed_form(self._rowid)
            M.mexec(str("LOCK -%s" % g_path))   # TODO: mexec to take unicode
            self._locked = False
            
    def _on_commit(self):
        if self._rowid:
            self._update()
        else:
            self._insert()
            
    def _on_abort(self):
        pass

    def _on_after_commit(self):
        self._unlock()
        self._changed = False
        self._changed_fields = []
            
    def _on_after_abort(self):
        self._unlock()
        self._changed = False
        self._changed_fields = []

        #   Any data in the object is dirty 
        #   this should force it to reload if it is accessed again
        if self._changed:
            self._stored_data = None

    @property
    def _data(self):
        # for lazy evaluation
        if self._stored_data is None:
            self._retrieve()
        return self._stored_data

    @property
    def _iens(self):
        if self._rowid is None:
            return "+1," # protocol used for inserting records, fileman pm 3-125
        else:
            return str(self._rowid) + ","

    def __str__(self):
        fields = self._dd.fields
        rv = ['DBSRow file=%s, fileid=%s, rowid=%s' % (self._dd.filename, self._dd.fileid, self._rowid)]
        keys = self.keys()
        keys.sort()
        for k in keys:
            v = self._data.get(k)
            if v:
                f = fields.get(k)
                if f:
                    fn = f.label
                else:
                    fn = "not in dd"
                rv.append('%s (%s) = "%s"' % (fn, k, v))
        return '\n'.join(rv)

    def keys(self):
        return self._data.keys()

    def items(self):
        return self._data.items()

    def __getitem__(self, fieldid, default=''):
        """
            Return a field using array notation

            print record[.01]

            Item does not exist, but is a valid fieldid, insert it.
            This occurs on an insert. The inserted field does not
            affect the transaction tracking.
        """

        fieldid = str(fieldid)
        try:
            return self._data[fieldid]
        except:
            if fieldid in self._fieldids:
                g = M.Globals()
                v = g[self._row_tmpid][self._dd.fileid][self._iens][fieldid]
                v.value = default
                self._stored_data[fieldid] = v
                v._on_before_change = lambda g,v,fieldid=fieldid: self._before_value_change(fieldid, g, v)
                return self[fieldid]

            raise FilemanError("""DBSRow (%s=%s): invalid attribute error""" %
                (self._dd.fileid, self._dd.filename), fieldid)

    def __getattr__(self, key):
        """
            Called for misses
        """
        fieldid = self._dd.attrs.get(key, None)
        if fieldid is not None:
            return self[fieldid]
        raise AttributeError(key)

    def __setattr__(self, key, value):
        """
            called by:

                record.FIELD = 4

            If FIELD exists, set its value
            If FIELD does not exist, and is in the data dictionary, create it.
            If FIELD does not exist, and is not the data dictionary, raise exception.
        """
        if key[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            return super(DBSRow, self).__setattr__(key, value)
        fieldid = self._dd.attrs.get(key, None)
        if fieldid is not None:
            self[fieldid].value = value
            return
        raise AttributeError(key)

    def __del__(self):
        # Each time we retrieve a row, it is copied to a temporary store. 
        # This needs to be killed or we have a memory leak in GT.M
        g = M.Globals()
        g[self._row_tmpid].kill()
        if self._row_fdaid:
            g[self._row_fdaid].kill()

    def _retrieve(self):
        """
            Retrieve values
            Internal or External
        """
        g = M.Globals()
        g["ERR"].kill()

        M.proc("GETS^DIQ",
            self._dd.fileid,      # numeric file id
            self._iens,           # IENS
            "*",                 # Fields to return TODO
            "N",                # Flags N=no nulls, R=return field names
            self._row_tmpid,
            "ERR")

        # Check for error
        err = g["ERR"]
        if err.exists():
            raise FilemanError("""DBSRow._retrieve() : FILEMAN Error : file [%s], fileid = [%s], rowid = [%s], fieldids = [%s]"""
                % (self._dd.filename, self._dd.fileid, self._rowid, "*"), str(err))

        # Extract the result and store in python variable
        self._stored_data = dict(g[self._row_tmpid][self._dd.fileid][self._iens])
        self._changed = False
        self._changed_fields = []

        # Add in trigger
        for key, value in self._stored_data.items():
            value._on_before_change = lambda g,v,fieldid=key: self._before_value_change(fieldid, g, v)

    def _create_fda(self):
        """
            For the current record, copy all changed fields to an FDA record
            (Fileman Data Array), see programmer manual 3.2.3

            FDA_ROOT(FILE#,"IENS",FIELD#)="VALUE"

        """
        g = M.Globals()
        self._row_fdaid = row_fdaid = "fda%s" % id(self)
        fda = g[row_fdaid]
        fda.kill()
        fileid = self._dd.fileid
        iens = self._iens
        for fieldid in self._changed_fields:
            fda[fileid][iens][fieldid].value = self[fieldid].value
        return row_fdaid

    def _insert(self):
        """
            Create a new record

            This is intended to be used during a transaction commit.

            UPDATE^DIE(FLAGS,FDA_ROOT,IEN_ROOT,MSG_ROOT)
        """
        g = M.Globals()
        g["ERR"].kill()

        # Create an FDA format array for fileman
        fdaid = self._create_fda()
        ienid = "ien%s" % id(self)

        # Flags:
        # E - use external formats
        # S - do not clear the row global
        M.proc("UPDATE^DIE", "ES" , fdaid, ienid, "ERR")

        # Check for error
        err = g["ERR"]
        if err.exists():

            # TODO: Work out the error codes.

            # ERR.DIERR.6.PARAM.0 = "3"
            # ERR.DIERR.6.PARAM.FIELD = "1901"
            # ERR.DIERR.6.PARAM.FILE = "2"
            # ERR.DIERR.6.PARAM.IENS = "+1,"
            # ERR.DIERR.6.TEXT.1 = "The new record '+1,' lacks some required identifiers."

            raise FilemanError("""DBSRow._update() : FILEMAN Error : file [%s], fileid = [%s], rowid = [%s]"""
                % (self._dd.filename, self._dd.fileid, self._rowid), str(err))
        
        # What is the id of the new record?
        self._rowid = int(g[ienid]['1'].value)
        self._stored_data = None

    def _update(self):
        """
            Write changed data back to the database.
            
            This is intended to be used during a transaction commit.
        """
        g = M.Globals()
        g["ERR"].kill()

        # Create an FDA format array for fileman
        fdaid = self._create_fda()

        # Flags:
        # E - use external formats
        # K - lock the record
        # S - do not clear the row global
        # T - verify the data
        M.proc("FILE^DIE", "EST" , fdaid, "ERR")

        # Check for error
        err = g["ERR"]
        if err.exists():
            raise FilemanError("""DBSRow._update() : FILEMAN Error : file [%s], fileid = [%s], rowid = [%s]"""
                % (self._dd.filename, self._dd.fileid, self._rowid), str(err))
