import json
import types
import base64
import struct
import logging
import collections

import regex

import synapse.exc as s_exc
import synapse.common as s_common
import synapse.dyndeps as s_dyndeps

import synapse.lib.chop as s_chop
import synapse.lib.time as s_time
import synapse.lib.syntax as s_syntax
import synapse.lib.modules as s_modules
import synapse.lib.msgpack as s_msgpack

import synapse.lookup.iso3166 as s_l_iso3166

logger = logging.getLogger(__name__)

class Type:

    _opt_defs = ()

    def __init__(self, modl, name, info, opts):
        '''
        Construct a new Type object.

        Args:
            modl (synpase.datamodel.DataModel): The data model instance.
            name (str): The name of the type.
            info (dict): The type info (docs etc).
            opts (dict): Options that are specific to the type.
        '''
        # these fields may be referenced by callers
        self.modl = modl
        self.name = name
        self.info = info
        self.form = None # this will reference a Form() if the type is a form

        self.opts = dict(self._opt_defs)
        self.opts.update(opts)

        self._type_norms = {}   # python type to norm function map str: _norm_str
        self._cmpr_ctors = {}   # cmpr string to filter function constructor map

        self.indxcmpr = {
            '=': self.indxByEq,
            '*in=': self.indxByIn,
            '*range=': self.indxByRange,
        }

        self.setCmprCtor('=', self._ctorCmprEq)

        self.postTypeInit()

    def setCmprCtor(self, name, func):
        self._cmpr_ctors[name] = func

    def getCmprCtor(self, name):
        return self._cmpr_ctors.get(name)

    def _ctorCmprEq(self, text):
        norm, info = self.norm(text)
        def cmpr(valu):
            return norm == valu
        return cmpr

    def indxByEq(self, valu):
        norm, info = self.norm(valu)
        indx = self.indx(norm)
        return (
            ('eq', indx),
        )

    def indxByIn(self, vals):

        opers = []
        if type(vals) not in (list, tuple):
            raise s_exc.BadCmprValu(valu=vals, cmpr='*in=')

        for valu in vals:
            opers.extend(self.getIndxOpers(valu))

        return opers

    def indxByRange(self, valu):

        if type(valu) not in (list, tuple):
            raise s_exc.BadCmprValu(valu=valu, cmpr='*range=')

        if len(valu) != 2:
            raise s_exc.BadCmprValu(valu=valu, cmpr='*range=')

        minv, _ = self.norm(valu[0])
        maxv, _ = self.norm(valu[1])

        mini = self.indx(minv)
        maxi = self.indx(maxv)

        return (
            ('range', (mini, maxi)),
        )

    def getFiltFunc(self, cmpr, text):
        '''
        Return a filter function for the given value and comparison.

        Args:
            cmpr (str): Comparison operator such as '='.
            text (str): The query text to compare against.
        '''
        ctor = self._cmpr_ctors.get(cmpr)
        if ctor is not None:
            return ctor(text)

        norm, info = self.norm(text)

        #cmprfunc = s_cmpr.get(cmpr)
        #if cmprfunc is None:
            #raise s_exc.NoSuchCmpr(name=cmpr)

        #def func(valu):

                #s_cmpr.
            #return cmprfunc(

    def setNormFunc(self, typo, func):
        '''
        Register a normalizer function for a given python type.

        Args:
            typo (type): A python type/class to normalize.
            func (function): A callback which normalizes a python value.
        '''
        self._type_norms[typo] = func

    def postTypeInit(self):
        pass

    def norm(self, valu):
        '''
        Normalize the value for a given type.

        Args:
            valu (obj): The value to normalize.

        Returns:
            ((obj,dict)): The normalized valu, info tuple.

        Notes:
            The info dictionary uses the following key conventions:
                subs (dict): The normalized sub-fields as name: valu entries.
        '''
        func = self._type_norms.get(type(valu))
        if func is None:
            raise s_exc.NoSuchFunc(mesg='no norm for type: %r' % (type(valu),))

        return func(valu)

    def repr(self, norm):
        return str(norm)

    def indx(self, norm):
        '''
        Return the property index bytes for the given *normalized* value.
        '''
        name = self.__class__.__name__
        raise s_exc.NoSuchImpl(name='%s.indx' % name)

    def merge(self, oldv, newv):
        '''
        Allow types to "merge" data from two sources based on value precidence.

        Args:
            valu (object): The current value.
            newv (object): The updated value.

        Returns:
            (object): The merged value.
        '''
        return newv

    def extend(self, name, opts, info):
        '''
        Extend this type to construct a sub-type.

        Args:
            name (str): The name of the new sub-type.
            opts (dict): The type options for the sub-type.
            info (dict): The type info for the sub-type.

        Returns:
            (synapse.types.Type): A new sub-type instance.
        '''
        tifo = self.info.copy()
        tifo.update(info)

        topt = self.opts.copy()
        topt.update(opts)

        return self.__class__(self.modl, name, tifo, topt)

    def clone(self, opts):
        '''
        Create a new instance of this type with the specified options.

        Args:
            opts (dict): The type specific options for the new instance.
        '''
        topt = self.opts.copy()
        topt.update(opts)
        return self.__class__(self.modl, self.name, self.info, topt)

    def getIndxOps(self, valu, cmpr='='):
        '''
        Return a list of index operation tuples to lift values in a table.

        Valid index operations include:
            ('eq', <indx>)
            ('pref', <indx>)
            ('range', (<minindx>, <maxindx>))
        '''
        func = self.indxcmpr.get(cmpr)

        if func is None:
            raise s_exc.NoSuchCmpr(type=self.name, cmpr=cmpr)

        return func(valu)

tagre = regex.compile(r'^([\w]+\.)*[\w]+$')

class Tag(Type):

    def postTypeInit(self):
        self.setNormFunc(str, self._normPyStr)
        self.indxcmpr['^='] = self.indxByPref

    def indxByPref(self, valu):
        norm, info = self.norm(valu)
        return (
            ('pref', norm.encode('utf8')),
        )

    def _normPyStr(self, text):

        valu = text.lower().strip('#').strip()
        toks = [v.strip() for v in valu.split('.')]

        subs = {
            'base': toks[-1],
            'depth': len(toks),
        }

        norm = '.'.join(toks)
        if not tagre.match(norm):
            raise s_exc.BadTypeValu(valu=text)

        if len(toks) > 1:
            subs['up'] = '.'.join(toks[:-1])

        return norm, {'subs': subs}

    def indx(self, norm):
        return norm.encode('utf8')

class Str(Type):

    _opt_defs = {
        ('regex', None),
        ('lower', False),
    }

    def postTypeInit(self):

        self.regex = None
        restr = self.opts.get('regex')
        if restr is not None:
            self.regex = regex.compile(restr)

        self.indxcmpr['^='] = self.indxByPref

    def indxByPref(self, valu):

        # doesnt have to be normable...
        if self.opts.get('lower'):
            valu = valu.lower()

        return (
            ('pref', valu.encode('utf8')),
        )

    def norm(self, valu):

        norm = str(valu)

        if self.opts['lower']:
            norm = norm.lower()

        if self.regex is not None:
            if self.regex.match(norm) is None:
                raise s_exc.BadTypeValu(name=self.name, valu=valu, mesg='regex does not match')

        return norm, {}

    def indx(self, norm):
        return norm.encode('utf8')

class Int(Type):

    _opt_defs = (

        ('size', 8),

        ('fmt', '%d'),

        ('min', None),
        ('max', None),

        ('ismin', False),
        ('ismax', False),

#        ('fmt', {'cast': 'str', 'defval': '%d',
#            'doc': 'Set to an integer compatible format string to control repr.'}),
#
#        ('size', {'cast': 'int', 'defval': 8,
#            'doc': 'Set the storage size of the integer type in bytes.'}),
#
#        ('max', {'cast': 'int', 'defval': None,
#            'doc': 'Set to a value to enforce maximum value for the type.'}),
#
#        ('min', {'cast': 'int', 'defval': None,
#            'doc': 'Set to a value to enforce minimum value for the type.'}),
#
#        ('ismin', {'cast': 'bool', 'defval': False,
#            'doc': 'Set to True to enable ismin behavior on value merge.'}),
#
#        ('ismax', {'cast': 'bool', 'defval': False,
#            'doc': 'Set to True to enable ismax behavior on value merge.'}),
    )

    def postTypeInit(self):
        self.minval = self.opts.get('min')
        self.maxval = self.opts.get('max')

        self.setNormFunc(str, self._normPyStr)
        self.setNormFunc(int, self._normPyInt)

    def merge(self, oldv, newv):

        if self.opts.get('ismin'):
            return min(oldv, newv)

        if self.opts.get('ismax'):
            return max(oldv, newv)

        return newv

    def cmprCtorEq(self, text):

        norm, info = self.norm(text)

        def cmpr(valu):
            return valu == norm

        return cmpr

    def _normPyStr(self, valu):
        return self._normPyInt(int(valu, 0))

    def _normPyInt(self, valu):

        if self.minval is not None and valu < self.minval:
            mesg = f'value is below min={self.minval}'
            raise s_exc.BadTypeValu(valu=valu, mesg=mesg)

        if self.maxval is not None and valu > self.maxval:
            mesg = f'value is below max={self.maxval}'
            raise s_exc.BadTypeValu(valu=valu, mesg=mesg)

        return valu, {}

    def indx(self, valu):
        size = self.opts.get('size')
        return valu.to_bytes(size, 'big')

class Bool(Type):

    def postTypeInit(self):
        self.setNormFunc(str, self._normPyStr)
        self.setNormFunc(int, self._normPyInt)
        self.setNormFunc(bool, self._normPyInt)

    def indx(self, norm):
        return norm.to_bytes(length=1, byteorder='big')

    def _normPyStr(self, valu):

        ival = s_common.intify(valu)
        if ival is not None:
            return int(bool(ival)), {}

        if valu in ('true', 't', 'y', 'yes', 'on'):
            return 1, {}

        if valu in ('false', 'f', 'n', 'no', 'off'):
            return 0, {}

        raise s_exc.BadTypeValu(name=self._type_name, valu=valu)

    def _normPyInt(self, valu):
        return int(bool(valu)), {}

    def repr(self, valu):
        return repr(bool(valu))

class Time(Type):

    _opt_defs = (
        ('ismin', False),
        ('ismax', False),
    )

    def postTypeInit(self):

        self.setNormFunc(int, self._normPyInt)
        self.setNormFunc(str, self._normPyStr)

        self.ismin = self.opts.get('ismin')
        self.ismax = self.opts.get('ismax')

    def _normPyStr(self, valu):

        valu = valu.strip().lower()
        if valu == 'now':
            return self._normPyInt(s_common.now())

        valu = s_time.parse(valu)
        return self._normPyInt(valu)

    def _normPyInt(self, valu):
        return valu, {}

    def merge(self, oldv, newv):

        if self.ismin:
            return min(oldv, newv)

        if self.ismax:
            return max(oldv, newv)

        return newv

    def repr(self, valu):
        return s_time.repr(valu)

    def indx(self, norm):
        # offset to prevent pre-epoch negative values from
        # wreaking havoc with the btree range indexing...
        return (norm + 0x8000000000000000).to_bytes(8, 'big')

    def _indxTimeRange(self, mint, maxt):
        minv, _ = self.norm(mint)
        maxv, _ = self.norm(maxt)
        return (
            ('range', (self.indx(minv), self.indx(maxv))),
        )

    def indxByEq(self, valu):

        if type(valu) == str and valu.endswith('*'):
            valu = s_chop.digits(valu)
            maxv = str(int(valu) + 1)
            return self._indxTimeRange(valu, maxv)

        return Type.indxByEq(self, valu)

class Ival(Type):

    def postTypeInit(self):
        self.timetype = self.modl.type('time')
        self.setNormFunc(int, self._normPyInt)
        self.setNormFunc(str, self._normPyStr)
        self.setNormFunc(list, self._normPyIter)
        self.setNormFunc(tuple, self._normPyIter)
        self.setNormFunc(None.__class__, self._normPyNone)

    def _normPyNone(self, valu):
        # none is an ok interval (unknown...)
        return valu, {}

    def _normPyInt(self, valu):
        return (valu, valu + 1), {}

    def _normPyStr(self, valu):
        norm, info = self.timetype.norm(valu)
        # until we support 2013+2years syntax...
        return (norm, norm + 1), {}

    def _normPyIter(self, valu):

        vals = [self.timetype.norm(v)[0] for v in valu]
        if len(vals) == 1:
            vals.append(vals[0] + 1)

        norm = (min(vals), max(vals))
        return norm, {}

    def indx(self, norm):

        if norm is None:
            return b''

        indx = self.timetype.indx(norm[0])
        indx += self.timetype.indx(norm[1])

        return indx

class Guid(Type):

    def postTypeInit(self):
        self.setNormFunc(str, self._normPyStr)

    def _normPyStr(self, valu):

        if valu == '*':
            valu = s_common.guid()
            return valu, {}

        valu = valu.lower()
        if not s_common.isguid(valu):
            raise s_exc.BadTypeValu(name=self.name, valu=valu)

        return valu, {}

    def indx(self, norm):
        return s_common.uhex(norm)

class Loc(Type):

    def postTypeInit(self):
        self.setNormFunc(str, self._normPyStr)

    def _normPyStr(self, valu):

        valu = valu.lower().strip()

        norms = []
        for part in valu.split('.'):
            part = ' '.join(part.split())
            norms.append(part)

        norm = '.'.join(norms)
        return norm, {}

    def indx(self, norm):
        parts = norm.split('.')
        valu = '\x00'.join(parts) + '\x00'
        return valu.encode('utf8')

    def indxByEq(self, valu):

        norm, info = self.norm(valu)
        indx = self.indx(norm)

        return (
            ('pref', indx),
        )

class Comp(Type):

    def postTypeInit(self):
        self.setNormFunc(list, self._normPyTuple)
        self.setNormFunc(tuple, self._normPyTuple)

    def _normPyTuple(self, valu):

        fields = self.opts.get('fields')
        if len(fields) != len(valu):
            raise s_exc.BadTypeValu(name=self.name, valu=valu)

        subs = {}
        norms = []

        for i, (name, typename) in enumerate(fields):

            _type = self.modl.type(typename)
            if _type is None:
                raise Exception('we need a postModelInit()?') # FIXME

            norm, info = _type.norm(valu[i])

            subs[name] = norm
            norms.append(norm)

        norm = tuple(norms)
        return norm, {'subs': subs}

    def indx(self, norm):
        return s_common.buid(norm)

class Hex(Type):
    _opt_defs = (
        ('size', 0),
    )

    def postTypeInit(self):
        self._size = self.opts.get('size')
        if self._size < 0:
            # zero means no width check
            raise s_exc.BadConfValu(name='size', valu=self._size,
                                    mesg='Size must be > 0')
        if self._size % 2 != 0:
            raise s_exc.BadConfValu(name='size', valu=self._size,
                                    mesg='Size must be a multiple of 2')
        self.setNormFunc(str, self._normPyStr)
        self.setNormFunc(bytes, self._normPyBytes)

    def indxByEq(self, valu):
        if isinstance(valu, str) and valu.endswith('*'):
            valu = valu.rstrip('*')
            norm = s_chop.hexstr(valu)
            return (
                ('pref', self.indx(norm)),
            )

        return Type.indxByEq(self, valu)

    def _normPyStr(self, valu):
        valu = s_chop.hexstr(valu)

        if self._size and len(valu) != self._size:
            raise s_exc.BadTypeValu(valu=valu, reqwidth=self._size,
                                    mesg='invalid width')
        return valu, {}

    def _normPyBytes(self, valu):
        return self._normPyStr(s_common.ehex(valu))

    def indx(self, norm):
        return s_common.uhex(norm)

class Ndef(Type):

    def postTypeInit(self):
        self.setNormFunc(list, self._normPyTuple)
        self.setNormFunc(tuple, self._normPyTuple)

    def _normPyTuple(self, valu):
        try:
            formname, formvalu = valu
        except Exception as e:
            raise s_exc.BadTypeValu(name=self.name, valu=valu)

        form = self.modl.form(formname)
        if form is None:
            raise s_exc.NoSuchForm(name=formname)

        formnorm, info = form.type.norm(formvalu)
        norm = (form.name, formnorm)

        adds = (norm,)
        subs = {'form': form.name}

        return norm, {'adds': adds, 'subs': subs}

    def indx(self, norm):
        return s_common.buid(norm)

class NodeProp(Type):

    def postTypeInit(self):
        self.setNormFunc(list, self._normPyTuple)
        self.setNormFunc(tuple, self._normPyTuple)

    def _normPyTuple(self, valu):
        try:
            propname, propvalu = valu
        except Exception as e:
            raise s_exc.BadTypeValu(name=self.name, valu=valu)

        prop = self.modl.prop(propname)
        if prop is None:
            raise s_exc.NoSuchProp(name=propname)

        propnorm, info = prop.type.norm(propvalu)
        return (prop.full, propnorm), {}

    def indx(self, norm):
        return s_common.buid(norm)

######################################################################
# TODO FROM HERE DOWN....
######################################################################

class JsonType(Type):

    def norm(self, valu, oldval=None):

        if not isinstance(valu, str):
            try:
                return json.dumps(valu, sort_keys=True, separators=(',', ':')), {}
            except Exception as e:
                raise s_exc.BadTypeValu(valu, mesg='Unable to normalize object as json.')

        try:
            return json.dumps(json.loads(valu), sort_keys=True, separators=(',', ':')), {}
        except Exception as e:
            raise s_exc.BadTypeValu(valu, mesg='Unable to norm json string')


def islist(x):
    return type(x) in (list, tuple)

class StormType(Type):

    def norm(self, valu, oldval=None):
        try:
            s_syntax.parse(valu)
        except Exception as e:
            raise s_exc.BadTypeValu(valu)
        return valu, {}

class PermType(Type):
    '''
    Enforce that the permission string and options are known.
    '''
    def norm(self, valu, oldval=None):

        try:
            pnfo, off = s_syntax.parse_perm(valu)
        except Exception as e:
            raise s_exc.BadTypeValu(valu)

        if off != len(valu):
            raise s_exc.BadTypeValu(valu)
        return valu, {}
