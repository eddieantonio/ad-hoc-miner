#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

# Copyright 2017 Eddie Antonio Santos <easantos@ualberta.ca>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Language definition for JavaScript.
"""

import json
import subprocess
import tempfile
from io import StringIO, IOBase
from pathlib import Path
from typing import Any, Callable, IO, Iterable, Sequence, Tuple, Union
from typing import cast

from sensibility.language import Language, SourceSummary
from sensibility.lexical_analysis import Token, Lexeme, Location, Position

here = Path(__file__).parent
esprima_bin = here / 'esprima-interface'
assert esprima_bin.exists()


class JavaScript(Language):
    extensions = {'.js'}

    def tokenize(self, source: Union[str, bytes, IO[bytes]]) -> Sequence[Token]:
        """
        Tokenizes the given JavaScript file.

        >>> tokens = javascript.tokenize('import $')
        >>> len(tokens)
        2
        """

        with SafeSourceFile(source) as source_file:
            status = _tokenize(source_file)

        return [
            from_esprima_format(tok)
            for tok in json.loads(status.stdout.decode('UTF-8'))
        ]

    def check_syntax(self, source: Union[str, bytes]) -> bool:
        with SafeSourceFile(source) as source_file:
            status = subprocess.run((str(esprima_bin), '--check-syntax'),
                                    check=False,
                                    stdin=source_file,
                                    stdout=subprocess.PIPE)
        return status.returncode == 0

    def summarize_tokens(self, source: Iterable[Token]) -> SourceSummary:
        tokens = list(source)
        unique_lines = set(lineno for token in tokens
                           for lineno in token.lines)

        return SourceSummary(sloc=len(unique_lines), n_tokens=len(tokens))

    def vocabularize_tokens(self, tokens: Iterable[Token]) -> Iterable[Tuple[Location, str]]:
        for token in tokens:
            yield token.location, stringify_lexeme(token)


class SafeSourceFile:
    """
    Context manager that always yields a IO[bytes] object, and safely closes
    it if it was created here.
    """

    def __init__(self, source: Union[str, bytes, IO[bytes]]) -> None:
        self.source = source
        self._owned: IO[bytes] = None
        self._foreign: IO[bytes] = None

    def __enter__(self) -> IO[bytes]:
        if isinstance(self.source, (str, bytes)):
            self._owned = synthetic_file(self.source)
        elif isinstance(self.source, IOBase):
            self._foreign = self.source
        else:
            raise ValueError(self.source)

        return self._owned or self._foreign

    def __exit__(self, *exc_info: Any) -> None:
        if self._owned is not None:
            self._owned.close()
        else:
            assert self._foreign is not None


def synthetic_file(source: Union[str, bytes]) -> IO[bytes]:
    """
    Creates a true file, readable-file with the given contents.
    """
    file_obj = tempfile.TemporaryFile(mode='w+b')
    if isinstance(source, str):
        file_obj.write(source.encode('UTF-8'))
    else:
        file_obj.write(source)
    file_obj.flush()
    file_obj.seek(0)
    return file_obj


def _tokenize(file_obj: IO[bytes]) -> subprocess.CompletedProcess:
    """
    Tokenizes a (real!) bytes file using Esprima.
    """
    return subprocess.run([str(esprima_bin)],
                          check=True,
                          stdin=file_obj,
                          stdout=subprocess.PIPE)


def from_esprima_format(token) -> Token:
    """
    Parses the Esprima's token format
    """
    loc = token['loc']
    return Token(name=token['type'],
                 value=token['value'],
                 start=Position(line=loc['start']['line'],
                                column=loc['start']['column']),
                 end=Position(line=loc['end']['line'],
                              column=loc['end']['column']))


class StringifyLexeme:
    """
    Converts a Lexeme to its vocabularized form.

    >>> stringify_lexeme(Lexeme(value='**=', name='Punctuator'))
    '**='
    >>> stringify_lexeme(Lexeme(value='var', name='Keyword'))
    'var'
    >>> stringify_lexeme(Lexeme(value='false', name='Boolean'))
    'false'
    >>> stringify_lexeme(Lexeme(value='null', name='Null'))
    'null'
    >>> stringify_lexeme(Lexeme(value='``', name='Template'))
    '<STANDALONE-TEMPLATE>'
    >>> stringify_lexeme(Lexeme(value='`${', name='Template'))
    '<TEMPLATE-HEAD>'
    >>> stringify_lexeme(Lexeme(value='}`', name='Template'))
    '<TEMPLATE-TAIL>'
    >>> stringify_lexeme(Lexeme(value='}  ${', name='Template'))
    '<TEMPLATE-MIDDLE>'
    >>> stringify_lexeme(Lexeme(value='"hello world"', name='String'))
    '<STRING>'
    >>> stringify_lexeme(Lexeme(value='💩', name='Identifier'))
    '<IDENTIFIER>'
    >>> stringify_lexeme(Lexeme(value='/g/i', name='RegularExpression'))
    '<REGEXP>'
    >>> stringify_lexeme(Lexeme(value='3.14', name='Numeric'))
    '<NUMBER>'
    """

    def __call__(self, token) -> str:
        try:
            fn = getattr(self, token.name)
        except AttributeError:
            raise TypeError(f'Unhandled type: {token.name}')
        return fn(token.value)

    def Boolean(self, text):
        return text

    def Identifier(self, text):
        return '<IDENTIFIER>'

    def Keyword(self, text):
        return text

    def Null(self, text):
        return 'null'

    def Numeric(self, text):
        return '<NUMBER>'

    def Punctuator(self, text):
        return text

    def String(self, text):
        return '<STRING>'

    def RegularExpression(self, text):
        return '<REGEXP>'

    def Template(self, text):
        assert len(text) >= 2
        if text.startswith('`'):
            if text.endswith('`'):
                return '<STANDALONE-TEMPLATE>'
            elif text.endswith('${'):
                return '<TEMPLATE-HEAD>'
        elif text.startswith('}'):
            if text.endswith('`'):
                return '<TEMPLATE-TAIL>'
            elif text.endswith('${'):
                return '<TEMPLATE-MIDDLE>'
        raise TypeError('Unhandled template literal: ' + text)


# The main exports.
javascript = JavaScript()
stringify_lexeme = cast(Callable[[Lexeme], str], StringifyLexeme())
