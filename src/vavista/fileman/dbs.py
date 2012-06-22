
"""
This is intended to provide a wrapping around the
fileman DBS API. This is a traditional data access API.

To understand the data dictionary, you have to go to the globals.

for file 999900

    zwrite ^DIC(999900,*)
    zwrite ^DD(999900,*)

"""

from vavista import M

# As per fm22_0um.pdf page 9-3
FT_DATETIME=1
FT_NUMERIC=2
FT_SET=3
FT_TEXT=4
FT_WP=5 
FT_COMPUTED=6
FT_POINTER=7
FT_VPOINTER=8
FT_MUMPS=9 
FT_SUBFILE=10 

class Field(object):
    fmql_type = None
    name = None
    fieldid = None

    # Storage is the global sub-index and either a "PIECE" within that value (1-99)
    # A NUMBER FROM 1 TO 99 OR AN $EXTRACT RANGE (E.G., "E2,4")
    storage = None

    mandatory = False
    details = None
    m_valid = None
    title = None
    fieldhelp = None

    def __init__(self, fieldid, name, fieldinfo):
        self.name = name
        self.fieldid = fieldid
        self._fieldinfo = fieldinfo # should not be used (debugging data)
        try:
            self.storage = fieldinfo[3]
        except:
            pass
        typespec = fieldinfo[0]
        self.mandatory = 'R' in typespec
        self.details = fieldinfo[2]
        if len(fieldinfo) > 4 and fieldinfo[4]:
            self.m_valid = fieldinfo[4]
        
        self.init_type(fieldinfo)

    def init_type(self, fieldinfo):
        # Implemented in subclass if required
        pass

    def __str__(self, msgs=[]):
        msgs = [] + msgs
        if self.mandatory: msgs.append("(mandatory)")
        if self.storage: msgs.append("location=%s" % self.storage)
        if self.details: msgs.append("details=%s" % self.details)
        if self.m_valid: msgs.append("valid=%s" % self.m_valid)
        if self.title: msgs.append("title='%s'" % self.title)
        if self.fieldhelp: msgs.append("fieldhelp='%s'" % self.fieldhelp)
        msgs.append("flags=%s" % self._fieldinfo[1])
        return "%s(%s=%s) %s" % (self.__class__.__name__, self.fieldid, self.name, " ".join(msgs))

    @classmethod
    def isa(cls, flags):
        """
            Determine whether the flags spec provided represents that type of Field
        """
        assert 0, "Must be implemented in Sub-Class"

class FieldDatetime(Field):
    fmql_type = FT_DATETIME

    @classmethod
    def isa(cls, flags):
        if flags and flags[0] == 'R': flags = flags[1:] # strip of mandatory flag
        return flags and flags[0] == 'D'
 
class FieldNumeric(Field):
    """
        Numeric fields have type specifiers - min/max digits
        J18,8 = maximum number of characters 18.
                number after the decimal point 8
                => 9 before it.
        The validation routine describes the min and max values, 

        Example (dumped wiht do ^%G:
            ^DD(999900,6,0)="f7^RNJ18,8^^2;2^K:+X'=X!(X>999999999)!(X<0)!(X?.E1"".""9N.N) X"
    """
    fmql_type = FT_NUMERIC

    @classmethod
    def isa(cls, flags):
        if flags and flags[0] == 'R': flags = flags[1:] # strip of mandatory flag
        return flags and flags[0] == 'N'
 
class FieldText(Field):
    fmql_type = FT_TEXT

    @classmethod
    def isa(cls, flags):
        if flags and flags[0] == 'R': flags = flags[1:] # strip of mandatory flag
        return flags and flags[0] == 'F'

class FieldSet(Field):
    fmql_type = FT_SET
    def init_type(self, fieldinfo):
        self.details = [i.split(":",1) for i in fieldinfo[2].split(';') if i]

    @classmethod
    def isa(cls, flags):
        if flags and flags[0] == 'R': flags = flags[1:] # strip of mandatory flag
        return flags and flags[0] == 'S'

class FieldWP(Field):
    fmql_type = FT_WP

    @classmethod
    def isa(cls, flags):
        if flags and flags[0] == 'R': flags = flags[1:] # strip of mandatory flag
        n=""
        for c in flags:
            if c not in "0123456789.": break
            n = n + c
        if len(n) > 0:
            s0, = M.func("$$VFILE^DILFD", n)
            return s0 == "0"
        return False

class FieldComputed(Field):
    fmql_type = FT_COMPUTED

    @classmethod
    def isa(cls, flags):
        if flags and flags[0] == 'R': flags = flags[1:] # strip of mandatory flag
        return flags and flags[0] == 'C'

class FieldPointer(Field):
    fmql_type = FT_POINTER

    @classmethod
    def isa(cls, flags):
        if flags and flags[0] == 'R': flags = flags[1:] # strip of mandatory flag
        return flags and flags[0] == 'P'

class FieldVPointer(Field):
    fmql_type = FT_VPOINTER

    @classmethod
    def isa(cls, flags):
        if flags and flags[0] == 'R': flags = flags[1:] # strip of mandatory flag
        return flags and flags[0] == 'V'

class FieldMUMPS(Field):
    fmql_type = FT_MUMPS

    @classmethod
    def isa(cls, flags):
        if flags and flags[0] == 'R': flags = flags[1:] # strip of mandatory flag
        return flags and flags[0] == 'K'

class FieldSubfile(Field):
    fmql_type = FT_SUBFILE

    @classmethod
    def isa(cls, flags):
        if flags and flags[0] == 'R': flags = flags[1:] # strip of mandatory flag
        n=""
        for c in flags:
            if c not in "0123456789.": break
            n = n + c
        if len(n) > 0:
            s0, = M.func("$$VFILE^DILFD", n)
            return s0 != "0"
        return False

# Simple lookup mechanism for parsing fields
FIELD_TYPES = [FieldText, FieldDatetime, FieldNumeric, FieldSet, FieldWP, FieldPointer,
    FieldVPointer, FieldMUMPS, FieldComputed, FieldSubfile]

class FilemanError(Exception):
    pass

class _DD(object):
    """
        Load the data dictionary for a FILE
    """
    _fileid = None
    _fields = None
    name = None

    def __init__(self, name):
        self.name = name

    def _clean_name(self, s):
        s = s.lower()
        s = ''.join([c for c in s if c in "_abcdefghijklmnopqrstuvwxyz0123456789 "])
        s = s.replace(' ', '_')
        return s

    @property
    def fileid(self):
        """
            Look up the ^DIC array and find the file number for the specified file, 
            e.g. FILE = 1 - result is a string.
        """
        if self._fileid is None:
            rv = M.mexec('''set s1=$order(^DIC("B",s0,0))''', self.name, M.INOUT(""))[0]
            if rv != '':
                self._fileid = rv
        return self._fileid

    @property
    def fields(self):
        """
            Return information about the dd fields
        """

        M.mexec('set U="^"') # DBS Calls Require this
        if self._fields is None:
            f = self._fields = {}
            fieldid = "0"
            while 1:
                # Subscript 0 is field description, .1 is the title, 3 is help
                fieldid, info, title, fieldhelp = M.mexec(
                    """set s0=$order(^DD(s2,s0)) Q:s0'=+s0  s s1=$G(^DD(s2,s0,0)),s3=$G(^DD(s2,s0,.1)),s4=$G(^DD(s2,s0,3))""",
                    M.INOUT(str(fieldid)), M.INOUT(""), str(self._fileid), M.INOUT(""), M.INOUT(""))
                if fieldid == "" or fieldid[0] not in "0123456789.":
                    break

                info = info.split("^") 
                name = self._clean_name(info[0])
                try:
                    ftype = info[1]
                except:
                    ftype = None
                if ftype:
                    finst = None
                    for klass in FIELD_TYPES:
                        if klass.isa(ftype):
                            finst = f[fieldid] = klass(fieldid, name, info)
                            break
                    assert finst, "FIELD [%s], spec [%s] was not identified" % (name, ftype)
                    finst.title = title
                    finst.fieldhelp = fieldhelp
                    print '\t', finst
                else:
                    assert finst, "FIELD [%s] %s has no fieldspec" % (name, info)

        return self._fields


def DD(name, cache={}):
    """
        Simple mechanism to cache DD objects.
    """
    if name not in cache:
        cache[name] = _DD(name)
    return cache[name]
    
class DBSFile(object):
    dd = None

    def __init__(self, dd):
        self.dd = dd
        assert (dd.fileid is not None)

    def __str__(self):
        return "DBSFILE %s (%s)" % (self.dd.name, self.dd.fileid)

    def get(self, rowid, fieldids=None):
        """
            Retrieve a row using the rowid.
            Return a dictionary of fieldids mapped to values
            If fieldids is not None, then we are only interested in the
            named fields.
            Do not load sub-tables.

            TODO: lots
        """
        M.mexec("kill ROW,ERR")
        iens = str(rowid) + ","
        M.proc("GETS^DIQ",
            self.dd.fileid,      # numeric file id
            iens,                # IENS
            "*",                 # Fields to return
            "NR",                # Flags N=no nulls, R=return field names
            "ROW",
            "ERR")

        # Check for error
        g = M.Globals()
        err = g["ERR"]
        if err.exists():
            raise FilemanError("""DBSFIle.get() : FILEMAN Error : file [%s], fileid = [%s], rowid = [%s], fieldids = [%s]"""
                % (self.dd.name, self.dd.fileid, rowid, fieldids), str(err))

        # Return result
        result = g["ROW"][self.dd.fileid][iens]
        return result.items()

class DBS(object):

    def __init__(self, DUZ, DT, isProgrammer=False):
        """
        """
        self.DUZ = DUZ
        self.DT = DT
        self.isProgrammer = isProgrammer
    def list_files(self):
        """
            Oddly, I cannot see how to list the files using the DBS API.
            This is required for debugging etc.
        """
        M.mexec('''set DUZ=s0,U="^"''', self.DUZ)
        if self.isProgrammer:
            M.mexec('''set DUZ(0)="@"''')
        rv = []
        s0 = "0"
        while s0 != "":
            s0, name = M.mexec(
                '''set s0=$order(^DIC(s0)) Q:s0'=+s0  I $D(^DIC(s0,0))&$D(^DIC(s0,0,"GL"))&$$VFILE^DILFD(s0) S s1=$P(^DIC(s0,0),U,1)''',
                M.INOUT(s0), M.INOUT(""))
            if name:
                rv.append((name, s0))
        return rv

    def get_file(self, name):
        """
            Look up the ^DIC array and find the file number for the specified file, 
            e.g. FILE = 1 - result is a string.
        """
        dd = DD(name)
        if dd.fileid is None:
            raise FilemanError("""DBS.get_file() : File not found [%s]""" % name)
        return DBSFile(dd)

    def dd(self, name):
        """
            Provided to expose the data dictionary via api
        """
        return DD(name)