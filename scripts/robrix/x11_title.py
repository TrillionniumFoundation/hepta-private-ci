"""Read ICCCM WM_NAME without treating legacy STRING bytes as UTF-8."""
import ctypes
import ctypes.util


def decode_title(encoding, raw):
    if encoding == 'UTF8_STRING':
        return raw.decode('utf-8', errors='strict')
    if encoding == 'STRING':
        return raw.decode('iso-8859-1', errors='strict')
    raise ValueError(f'Unsupported X11 title encoding: {encoding}')


def read_title(window):
    class TextProperty(ctypes.Structure):
        _fields_ = [('value', ctypes.c_void_p), ('encoding', ctypes.c_ulong),
                    ('format', ctypes.c_int), ('nitems', ctypes.c_ulong)]
    library = ctypes.util.find_library('X11')
    if library is None:
        raise RuntimeError('X11 title reader requires official libX11')
    x11 = ctypes.CDLL(library)
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XGetTextProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(TextProperty), ctypes.c_ulong]
    x11.XGetTextProperty.restype = ctypes.c_int
    x11.XGetAtomName.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XGetAtomName.restype = ctypes.c_void_p
    x11.XFree.argtypes = [ctypes.c_void_p]
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError('Unable to open fixture X11 display')
    prop = TextProperty()
    atom_name = None
    try:
        atom = x11.XInternAtom(display, b'WM_NAME', 0)
        if not x11.XGetTextProperty(display, int(window), ctypes.byref(prop), atom):
            raise RuntimeError('Fixture window has no WM_NAME')
        if prop.format != 8 or not 0 < prop.nitems <= 4096:
            raise ValueError('Unexpected X11 title property format/size')
        atom_name = x11.XGetAtomName(display, prop.encoding)
        if not atom_name:
            raise ValueError('Missing X11 title encoding name')
        encoding = ctypes.string_at(atom_name).decode('ascii', errors='strict')
        raw = ctypes.string_at(prop.value, prop.nitems)
        return {'encoding': encoding, 'rawHex': raw.hex(), 'title': decode_title(encoding, raw)}
    finally:
        if atom_name:
            x11.XFree(atom_name)
        if prop.value:
            x11.XFree(prop.value)
        x11.XCloseDisplay(display)
