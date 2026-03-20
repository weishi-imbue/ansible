from __future__ import annotations

from ansible.plugins.shell.powershell import _parse_clixml, ShellModule


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
                    b'<S S="Error">    + FullyQualifiedErrorId : CommandNotFoundException_x000D__x000A_</S><S S="Error"> _x000D__x000A_</S>' \
                    b'</Objs>'
    expected = b"fake : The term 'fake' is not recognized as the name of a cmdlet. Check \r\n" \
               b"the spelling of the name, or if a path was included.\r\n" \
               b"At line:1 char:1\r\n" \
               b"+ fake cmdlet\r\n" \
               b"+ ~~~~\r\n" \
               b"    + CategoryInfo          : ObjectNotFound: (fake:String) [], CommandNotFoundException\r\n" \
               b"    + FullyQualifiedErrorId : CommandNotFoundException\r\n "
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
                      b'</Objs>'
    expected = b"hi info"
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


def test_parse_clixml_escape_sequences_basic():
    """Test basic escape sequence decoding"""
    basic_escapes = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                   b'<S S="Error">Hello_x0020_World_x0021_</S>' \
                   b'</Objs>'
    expected = b"Hello World!"
    actual = _parse_clixml(basic_escapes)
    assert actual == expected


def test_parse_clixml_escape_sequences_control_chars():
    """Test control character escape sequences"""
    control_chars = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                   b'<S S="Error">Line1_x000D__x000A_Line2</S>' \
                   b'</Objs>'
    expected = b"Line1\r\nLine2"
    actual = _parse_clixml(control_chars)
    assert actual == expected


def test_parse_clixml_escape_sequences_lowercase():
    """Test lowercase hexadecimal escape sequences"""
    lowercase = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
               b'<S S="Error">Test_x005f_lowercase</S>' \
               b'</Objs>'
    expected = b"Test_lowercase"
    actual = _parse_clixml(lowercase)
    assert actual == expected


def test_parse_clixml_escape_sequences_surrogate_pair():
    """Test UTF-16 surrogate pair decoding (emoji)"""
    # _xD83D__xDE00_ is the surrogate pair for U+1F600 (😀)
    surrogate_pair = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                    b'<S S="Error">Hello_xD83D__xDE00_World</S>' \
                    b'</Objs>'
    expected = "Hello😀World".encode('utf-8')
    actual = _parse_clixml(surrogate_pair)
    assert actual == expected


def test_parse_clixml_escape_sequences_multiple_surrogate_pairs():
    """Test multiple UTF-16 surrogate pairs"""
    # _xD83D__xDE00_ is 😀, _xD83D__xDE0E_ is 😎
    multiple_pairs = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                    b'<S S="Error">_xD83D__xDE00__xD83D__xDE0E_</S>' \
                    b'</Objs>'
    expected = "😀😎".encode('utf-8')
    actual = _parse_clixml(multiple_pairs)
    assert actual == expected


def test_parse_clixml_escape_sequences_unpaired_high_surrogate():
    """Test unpaired high surrogate (should be preserved)"""
    # _xD83D_ without a following low surrogate
    unpaired_high = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                   b'<S S="Error">Test_xD83D_End</S>' \
                   b'</Objs>'
    # Unpaired high surrogate should be preserved using surrogatepass
    expected = "Test\ud83dEnd".encode('utf-8', 'surrogatepass')
    actual = _parse_clixml(unpaired_high)
    assert actual == expected


def test_parse_clixml_escape_sequences_unpaired_low_surrogate():
    """Test unpaired low surrogate"""
    # _xDC00_ is a low surrogate without a preceding high surrogate
    unpaired_low = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                  b'<S S="Error">Test_xDC00_End</S>' \
                  b'</Objs>'
    # Unpaired low surrogate should be preserved
    expected = "Test\udc00End".encode('utf-8', 'surrogatepass')
    actual = _parse_clixml(unpaired_low)
    assert actual == expected


def test_parse_clixml_escape_sequences_x005f_standalone():
    """Test _x005F_ standalone (should remain unchanged)"""
    x005f_standalone = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                      b'<S S="Error">Test_x005F_End</S>' \
                      b'</Objs>'
    expected = b"Test_x005F_End"
    actual = _parse_clixml(x005f_standalone)
    assert actual == expected


def test_parse_clixml_escape_sequences_x005f_lowercase():
    """Test _x005f_ standalone lowercase (should remain unchanged)"""
    x005f_lowercase = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                     b'<S S="Error">Test_x005f_End</S>' \
                     b'</Objs>'
    expected = b"Test_x005f_End"
    actual = _parse_clixml(x005f_lowercase)
    assert actual == expected


def test_parse_clixml_escape_sequences_x005f_before_escape():
    """Test _x005F_ followed by another escape (should decode to underscore)"""
    x005f_before_escape = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                         b'<S S="Error">Test_x005F__x0041_End</S>' \
                         b'</Objs>'
    expected = b"Test_AEnd"
    actual = _parse_clixml(x005f_before_escape)
    assert actual == expected


def test_parse_clixml_escape_sequences_x005f_lowercase_before_escape():
    """Test _x005f_ (lowercase) followed by another escape"""
    x005f_lower_before = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                        b'<S S="Error">Test_x005f__x0041_End</S>' \
                        b'</Objs>'
    expected = b"Test_AEnd"
    actual = _parse_clixml(x005f_lower_before)
    assert actual == expected


def test_parse_clixml_escape_sequences_invalid_hex():
    """Test invalid escape sequence (should remain unchanged)"""
    invalid_escape = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                    b'<S S="Error">Test_x005G_End</S>' \
                    b'</Objs>'
    expected = b"Test_x005G_End"
    actual = _parse_clixml(invalid_escape)
    assert actual == expected


def test_parse_clixml_escape_sequences_incomplete():
    """Test incomplete escape sequence (should remain unchanged)"""
    incomplete = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                b'<S S="Error">Test_x00</S>' \
                b'</Objs>'
    expected = b"Test_x00"
    actual = _parse_clixml(incomplete)
    assert actual == expected


def test_parse_clixml_escape_sequences_mixed():
    """Test mixed escape sequences and regular text"""
    mixed = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
           b'<S S="Error">Error_x0020_message:_x000D__x000A_Failed_x0021_</S>' \
           b'</Objs>'
    expected = b"Error message:\r\nFailed!"
    actual = _parse_clixml(mixed)
    assert actual == expected


def test_parse_clixml_escape_sequences_unicode_symbols():
    """Test various Unicode symbols"""
    # _x263A_ is ☺ (smiley face)
    unicode_symbols = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                     b'<S S="Error">Smiley_x263A_Face</S>' \
                     b'</Objs>'
    expected = "Smiley☺Face".encode('utf-8')
    actual = _parse_clixml(unicode_symbols)
    assert actual == expected


def test_parse_clixml_escape_sequences_no_extra_newline():
    """Test that no extra newline is appended at the end"""
    single_line = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                 b'<S S="Error">Single_x0020_Line</S>' \
                 b'</Objs>'
    expected = b"Single Line"
    actual = _parse_clixml(single_line)
    assert actual == expected
    # Ensure no trailing newline
    assert not actual.endswith(b'\r\n')


def test_parse_clixml_multiple_objs_separator():
    """Test that results from different Objs blocks are separated by \\r\\n"""
    multiple_objs = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                   b'<S S="Error">Block_x0020_1</S>' \
                   b'</Objs>' \
                   b'<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                   b'<S S="Error">Block_x0020_2</S>' \
                   b'</Objs>'
    expected = b"Block 1\r\nBlock 2"
    actual = _parse_clixml(multiple_objs)
    assert actual == expected


def test_parse_clixml_consecutive_s_elements_no_separator():
    """Test that consecutive S elements within same Objs block have no separator"""
    consecutive_s = b'#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">' \
                   b'<S S="Error">Part_x0020_1</S>' \
                   b'<S S="Error">Part_x0020_2</S>' \
                   b'</Objs>'
    expected = b"Part 1Part 2"
    actual = _parse_clixml(consecutive_s)
    assert actual == expected


def test_join_path_unc():
    pwsh = ShellModule()
    unc_path_parts = ['\\\\host\\share\\dir1\\\\dir2\\', '\\dir3/dir4', 'dir5', 'dir6\\']
    expected = '\\\\host\\share\\dir1\\dir2\\dir3\\dir4\\dir5\\dir6'
    actual = pwsh.join_path(*unc_path_parts)
    assert actual == expected
