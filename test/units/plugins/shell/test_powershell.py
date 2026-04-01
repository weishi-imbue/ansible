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


def test_replace_stderr_clixml_no_clixml():
    """Test that non-CLIXML stderr is returned unchanged."""
    stderr = b"normal error message\r\nline two\r\nline three"
    result = _replace_stderr_clixml(stderr)
    assert result == stderr


def test_replace_stderr_clixml_basic():
    """Test basic CLIXML replacement functionality."""
    stderr = b"#< CLIXML\r\n<Objs Version=\"1.1.0.1\" xmlns=\"http://schemas.microsoft.com/powershell/2004/04\">" \
             b"<S S=\"Error\">test error_x000D__x000A_</S></Objs>"
    result = _replace_stderr_clixml(stderr)
    expected = b"test error"
    assert result == expected


def test_replace_stderr_clixml_with_prefix_and_suffix():
    """Test CLIXML with non-CLIXML content before and after."""
    stderr = b"prefix line\r\n#< CLIXML\r\n<Objs Version=\"1.1.0.1\" xmlns=\"http://schemas.microsoft.com/powershell/2004/04\">" \
             b"<S S=\"Error\">test error_x000D__x000A_</S></Objs>\r\nsuffix line"
    result = _replace_stderr_clixml(stderr)
    expected = b"prefix line\r\ntest error\r\nsuffix line"
    assert result == expected


def test_replace_stderr_clixml_no_spurious_blank_lines():
    """Test fix for spurious blank lines (review comment 1, issue 1)."""
    # CLIXML block that produces output ending with \r\n
    stderr = b"prefix\r\n#< CLIXML\r\n<Objs Version=\"1.1.0.1\" xmlns=\"http://schemas.microsoft.com/powershell/2004/04\">" \
             b"<S S=\"Error\">Error message_x000D__x000A_</S></Objs>\r\nsuffix"
    result = _replace_stderr_clixml(stderr)
    expected = b"prefix\r\nError message\r\nsuffix"
    assert result == expected
    # Ensure no double \r\n (which would appear as empty line)
    assert b"\r\n\r\n" not in result


def test_replace_stderr_clixml_empty_clixml_no_blank_lines():
    """Test fix for spurious blank lines (review comment 1, issue 2)."""
    # CLIXML block with only progress data (returns empty bytes)
    stderr = b"line1\r\n#< CLIXML\r\n<Objs Version=\"1.1.0.1\" xmlns=\"http://schemas.microsoft.com/powershell/2004/04\">" \
             b"<Obj S=\"progress\" RefId=\"0\"><TN RefId=\"0\"><T>System.Management.Automation.PSCustomObject</T>" \
             b"<T>System.Object</T></TN><MS><I64 N=\"SourceId\">1</I64><PR N=\"Record\">" \
             b"<AV>Preparing modules for first use.</AV><AI>0</AI><Nil /><PI>-1</PI><PC>-1</PC>" \
             b"<T>Completed</T><SR>-1</SR><SD> </SD></PR></MS></Obj></Objs>\r\nline2"
    result = _replace_stderr_clixml(stderr)
    expected = b"line1\r\nline2"
    assert result == expected
    # Ensure no blank lines where CLIXML was
    assert b"\r\n\r\n" not in result


def test_replace_stderr_clixml_multiple_blocks_separate_lines():
    """Test fix for multiple CLIXML blocks on separate lines (review comment 2)."""
    stderr = b"#< CLIXML\r\n<Objs Version=\"1.1.0.1\" xmlns=\"http://schemas.microsoft.com/powershell/2004/04\">" \
             b"<S S=\"Error\">Error 1</S></Objs>\r\n" \
             b"<Objs Version=\"1.1.0.1\" xmlns=\"http://schemas.microsoft.com/powershell/2004/04\">" \
             b"<S S=\"Error\">Error 2</S></Objs>"
    result = _replace_stderr_clixml(stderr)
    expected = b"Error 1\r\nError 2"
    assert result == expected


def test_replace_stderr_clixml_with_trailing_data():
    """Test CLIXML with trailing data on same line after </Objs>."""
    stderr = b"#< CLIXML\r\n<Objs Version=\"1.1.0.1\" xmlns=\"http://schemas.microsoft.com/powershell/2004/04\">" \
             b"<S S=\"Error\">test</S></Objs>trailing data"
    result = _replace_stderr_clixml(stderr)
    expected = b"testtrailing data"
    assert result == expected


def test_replace_stderr_clixml_incomplete_block():
    """Test that incomplete CLIXML blocks are left unchanged."""
    stderr = b"#< CLIXML\r\n<Objs Version=\"1.1.0.1\" xmlns=\"http://schemas.microsoft.com/powershell/2004/04\">" \
             b"<S S=\"Error\">incomplete"
    result = _replace_stderr_clixml(stderr)
    # Should return original unchanged
    assert result == stderr


def test_replace_stderr_clixml_invalid_xml():
    """Test that invalid XML in CLIXML block is left unchanged."""
    stderr = b"#< CLIXML\r\n<Objs Version=\"1.1.0.1\" xmlns=\"http://schemas.microsoft.com/powershell/2004/04\">" \
             b"<S S=\"Error\">invalid xml<unclosed></Objs>"
    result = _replace_stderr_clixml(stderr)
    # Should return original unchanged due to XML parsing error
    assert result == stderr


def test_join_path_unc():
    pwsh = ShellModule()
    unc_path_parts = ['\\\\host\\share\\dir1\\\\dir2\\', '\\dir3/dir4', 'dir5', 'dir6\\']
    expected = '\\\\host\\share\\dir1\\dir2\\dir3\\dir4\\dir5\\dir6'
    actual = pwsh.join_path(*unc_path_parts)
    assert actual == expected
