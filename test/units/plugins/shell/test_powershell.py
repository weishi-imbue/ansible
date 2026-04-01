from __future__ import annotations

import pytest

from ansible.plugins.shell.powershell import _parse_clixml, _replace_stderr_clixml, ShellModule


def test_parse_clixml_empty():
    empty = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04"></Objs>'
    expected = b''
    actual = _parse_clixml(empty)
    assert actual == expected


def test_parse_clixml_with_progress():
    progress = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
               b'<Obj S="progress" RefId="0"><TN RefId="0"><T>System.Management.Automation.PSCustomObject</T><T>System.Object</T></TN><MS>' \
               b'<I64 N="SourceId">1</I64><PR N="Record"><AV>Preparing modules for first use.</AV><AI>0</AI><Nil />' \
               b'<PI>-1</PI><PC>-1</PC><T>Completed</T><SR>-1</SR><SD> </SD></PR></MS></Obj></Objs>'
    expected = b''
    actual = _parse_clixml(progress)
    assert actual == expected


def test_parse_clixml_single_stream():
    single_stream = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                    b'<S S="Error">fake : The term \'fake\' is not recognized as the name of a cmdlet. Check _x000D__x000A_</S>' \
                    b'<S S="Error">the spelling of the name, or if a path was included._x000D__x000A_</S>' \
                    b'<S S="Error">At line:1 char:1_x000D__x000A_</S>' \
                    b'<S S="Error">+ fake cmdlet_x000D__x000A_</S><S S="Error">+ ~~~~_x000D__x000A_</S>' \
                    b'<S S="Error">    + CategoryInfo          : ObjectNotFound: (fake:String) [], CommandNotFoundException_x000D__x000A_</S>' \
                    b'<S S="Error">    + FullyQualifiedErrorId : CommandNotFoundException_x000D__x000A_</S>' \
                    b'<S S="Error"> _x000D__x000A_</S>' \
                    b'</Objs>'
    expected = b"fake : The term 'fake' is not recognized as the name of a cmdlet. Check \r\n" \
               b"the spelling of the name, or if a path was included.\r\n" \
               b"At line:1 char:1\r\n" \
               b"+ fake cmdlet\r\n" \
               b"+ ~~~~\r\n" \
               b"    + CategoryInfo          : ObjectNotFound: (fake:String) [], CommandNotFoundException\r\n" \
               b"    + FullyQualifiedErrorId : CommandNotFoundException\r\n" \
               b" \r\n"
    actual = _parse_clixml(single_stream)
    assert actual == expected


def test_parse_clixml_multiple_streams():
    multiple_stream = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                      b'<S S="Error">fake : The term \'fake\' is not recognized as the name of a cmdlet. Check _x000D__x000A_</S>' \
                      b'<S S="Error">the spelling of the name, or if a path was included._x000D__x000A_</S>' \
                      b'<S S="Error">At line:1 char:1_x000D__x000A_</S>' \
                      b'<S S="Error">+ fake cmdlet_x000D__x000A_</S><S S="Error">+ ~~~~_x000D__x000A_</S>' \
                      b'<S S="Error">    + CategoryInfo          : ObjectNotFound: (fake:String) [], CommandNotFoundException_x000D__x000A_</S>' \
                      b'<S S="Error">    + FullyQualifiedErrorId : CommandNotFoundException_x000D__x000A_</S><S S="Error"> _x000D__x000A_</S>' \
                      b'<S S="Info">hi info</S>' \
                      b'<S S="Info">other</S>' \
                      b'</Objs>'
    expected = b"hi infoother"
    actual = _parse_clixml(multiple_stream, stream="Info")
    assert actual == expected


def test_parse_clixml_multiple_elements():
    multiple_elements = b'#< CLIXML\r\n#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                        b'<Obj S="progress" RefId="0"><TN RefId="0"><T>System.Management.Automation.PSCustomObject</T><T>System.Object</T></TN><MS>' \
                        b'<I64 N="SourceId">1</I64><PR N="Record"><AV>Preparing modules for first use.</AV><AI>0</AI><Nil />' \
                        b'<PI>-1</PI><PC>-1</PC><T>Completed</T><SR>-1</SR><SD> </SD></PR></MS></Obj>' \
                        b'<S S="Error">Error 1</S></Objs>' \
                        b'<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04"><Obj S="progress" RefId="0">' \
                        b'<TN RefId="0"><T>System.Management.Automation.PSCustomObject</T><T>System.Object</T></TN><MS>' \
                        b'<I64 N="SourceId">1</I64><PR N="Record"><AV>Preparing modules for first use.</AV><AI>0</AI><Nil />' \
                        b'<PI>-1</PI><PC>-1</PC><T>Completed</T><SR>-1</SR><SD> </SD></PR></MS></Obj>' \
                        b'<Obj S="progress" RefId="1"><TNRef RefId="0" /><MS><I64 N="SourceId">2</I64>' \
                        b'<PR N="Record"><AV>Preparing modules for first use.</AV><AI>0</AI><Nil />' \
                        b'<PI>-1</PI><PC>-1</PC><T>Completed</T><SR>-1</SR><SD> </SD></PR></MS></Obj>' \
                        b'<S S="Error">Error 2</S></Objs>'
    expected = b"Error 1\r\nError 2"
    actual = _parse_clixml(multiple_elements)
    assert actual == expected


@pytest.mark.parametrize('clixml, expected', [
    ('', ''),
    ('just newline _x000A_', 'just newline \n'),
    ('surrogate pair _xD83C__xDFB5_', 'surrogate pair 🎵'),
    ('null char _x0000_', 'null char \0'),
    ('normal char _x0061_', 'normal char a'),
    ('escaped literal _x005F_x005F_', 'escaped literal _x005F_'),
    ('underscope before escape _x005F__x000A_', 'underscope before escape _\n'),
    ('surrogate high _xD83C_', 'surrogate high \uD83C'),
    ('surrogate low _xDFB5_', 'surrogate low \uDFB5'),
    ('lower case hex _x005f_', 'lower case hex _'),
    ('invalid hex _x005G_', 'invalid hex _x005G_'),
])
def test_parse_clixml_with_comlex_escaped_chars(clixml, expected):
    clixml_data = (
        '<# CLIXML\r\n'
        '<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">'
        f'<S S="Error">{clixml}</S>'
        '</Objs>'
    ).encode()
    b_expected = expected.encode(errors="surrogatepass")

    actual = _parse_clixml(clixml_data)
    assert actual == b_expected


def test_join_path_unc():
    pwsh = ShellModule()
    unc_path_parts = ['\\\\host\\share\\dir1\\\\dir2\\', '\\dir3/dir4', 'dir5', 'dir6\\']
    expected = '\\\\host\\share\\dir1\\dir2\\dir3\\dir4\\dir5\\dir6'
    actual = pwsh.join_path(*unc_path_parts)
    assert actual == expected


def test_replace_stderr_clixml_no_clixml():
    """Test that non-CLIXML content is preserved unchanged"""
    stderr = b"Some regular error\r\nAnother line\r\n"
    expected = stderr
    actual = _replace_stderr_clixml(stderr)
    assert actual == expected


def test_replace_stderr_clixml_simple_block():
    """Test basic CLIXML replacement"""
    stderr = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
             b'<S S="Error">test error_x000D__x000A_</S></Objs>'
    expected = b'test error'  # Note: trailing \r\n stripped to prevent double line break
    actual = _replace_stderr_clixml(stderr)
    assert actual == expected


def test_replace_stderr_clixml_with_non_clixml_content():
    """Test CLIXML replacement with surrounding non-CLIXML content"""
    stderr = b'Before content\r\n' \
             b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
             b'<S S="Error">test error_x000D__x000A_</S></Objs>\r\n' \
             b'After content'
    expected = b'Before content\r\ntest error\r\nAfter content'
    actual = _replace_stderr_clixml(stderr)
    assert actual == expected


def test_replace_stderr_clixml_empty_block():
    """Test empty CLIXML blocks don't inject spurious blank lines (Review Comment 1)"""
    stderr = b'Before\r\n' \
             b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04"></Objs>\r\n' \
             b'After'
    expected = b'Before\r\nAfter'  # No empty line where empty CLIXML block was
    actual = _replace_stderr_clixml(stderr)
    assert actual == expected


def test_replace_stderr_clixml_multiple_blocks():
    """Test multiple separate CLIXML blocks are all decoded (Review Comment 2)"""
    stderr = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
             b'<S S="Error">Error 1_x000D__x000A_</S></Objs>\r\n' \
             b'<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
             b'<S S="Error">Error 2_x000D__x000A_</S></Objs>'
    # _parse_clixml adds a separator between multiple <Objs> elements
    expected = b'Error 1\r\n\r\nError 2'  # Both blocks decoded with separator, trailing \r\n stripped
    actual = _replace_stderr_clixml(stderr)
    assert actual == expected


def test_replace_stderr_clixml_trailing_content_after_block():
    """Test trailing content on same line as </Objs> is preserved"""
    stderr = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
             b'<S S="Error">test error_x000D__x000A_</S></Objs> trailing content'
    expected = b'test error trailing content'  # Decoded content plus trailing preserved
    actual = _replace_stderr_clixml(stderr)
    assert actual == expected


def test_replace_stderr_clixml_incomplete_block():
    """Test incomplete CLIXML blocks are left unchanged"""
    stderr = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
             b'<S S="Error">incomplete'
    expected = stderr  # Should be unchanged since no closing </Objs>
    actual = _replace_stderr_clixml(stderr)
    assert actual == expected


def test_replace_stderr_clixml_no_trailing_newline_injection():
    """Test that parsed content ending with \\r\\n doesn't create double line breaks (Review Comment 1)"""
    stderr = b'Before\r\n' \
             b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
             b'<S S="Error">error with newline_x000D__x000A_</S></Objs>\r\n' \
             b'After'
    # _parse_clixml typically returns "error with newline\r\n", but we strip the \r\n
    # so when joined with \r\n separator, we get single line breaks, not double
    expected = b'Before\r\nerror with newline\r\nAfter'
    actual = _replace_stderr_clixml(stderr)
    assert actual == expected
