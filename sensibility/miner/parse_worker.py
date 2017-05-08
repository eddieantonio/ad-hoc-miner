#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

# Copyright 2016 Eddie Antonio Santos <easantos@ualberta.ca>
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
Listens to updates on q:analyze, and inserts them into the database.
"""

import json
import logging
import tempfile
from collections import Counter

import sh
from sh import node

from miner_db import Database
from miner_db.datatypes import ParsedSource
from rqueue import Queue, WorkQueue
from connection import redis_client, sqlite3_connection

from names import PARSE_QUEUE as QUEUE_NAME, CHAR_COUNT
QUEUE_ERRORS = QUEUE_NAME.errors

logger = logging.getLogger('parse_worker')


class ParseError(Exception):
    def __init__(self):
        super(ParseError, self).__init__('failed to parse file')


def parse_js(source):
    r"""
    >>> tokens, ast = parse_js("void 0;")
    >>> len(tokens)
    3
    >>> isinstance(ast, dict)
    True
    >>> parse_js("%$")
    Traceback (most recent call last):
    ...
    parse_worker.ParseError: failed to parse file

    >>> tokens, _ = parse_js("#!/usr/bin/node\nvar foo;")
    >>> len(tokens)
    3

    >>> tokens, _ = parse_js("/*\n*/\n\nimport * as esprima from 'esprima';")
    >>> len(tokens)
    7
    """

    if isinstance(source, str):
        source = source.encode('utf-8')

    with tempfile.NamedTemporaryFile() as source_file:
        source_file.write(source)
        source_file.flush()
        try:
            result_string = node('parse-js', source_file.name)
        except sh.ErrorReturnCode_1:
            raise ParseError
    result = json.loads(str(result_string))
    return result['tokens'], result['ast']


def in_uplus_notation(character):
    """
    >>> in_uplus_notation("a")
    'U+0061'
    >>> in_uplus_notation("😀")
    'U+1F600'
    """
    ordinal = ord(character)
    if ordinal > 0xFFFF:
        return "U+{:5X}".format(ordinal)
    else:
        return "U+{:04X}".format(ordinal)


def clean_literal(literal):
    """
    >>> clean_literal("''")
    ''
    >>> clean_literal('""')
    ''
    >>> clean_literal('"hello"')
    'hello'
    >>> clean_literal("'hello'")
    'hello'
    """
    assert len(literal) >= 2
    return literal[1:-1]


def clean_template(literal):
    r"""
    >>> clean_template("}`")
    ''
    >>> clean_template("}!`")
    '!'
    >>> clean_template("`${")
    ''
    >>> clean_template("`Hello, ${")
    'Hello, '
    """
    end_trim = 1
    if literal.endswith('${'):
        end_trim = 2
    return literal[1:-end_trim]


def find_literals(tokens):
    for token in tokens:
        if token['type'] == 'String':
            yield clean_literal(token['value'])
        if token['type'] == 'Template':
            yield clean_template(token['value'])


def count_codepoints_in_literals(tokens):
    r"""
    Counts codepoints in literals.
    >>> tokens, _ = parse_js('''""; ''; `${hello}, ${world}`; '😘';''')
    >>> counts = count_codepoints_in_literals(tokens)
    >>> counts == Counter({'U+0020': 1, 'U+1F618': 1, 'U+002C': 1})
    True
    """
    counter = Counter()
    for literal in find_literals(tokens):
        for scalar_value in literal:
            counter[in_uplus_notation(scalar_value)] += 1
    return counter


def insert_count(counter, client=redis_client):
    """
    >>> import redis
    >>> client = redis.StrictRedis(db=1)
    >>> client.delete(CHAR_COUNT) or 1
    1
    >>> insert_count(Counter({'U+0041': 2}), client=client)
    >>> int(client.zscore(CHAR_COUNT, 'U+0041'))
    2
    """
    with client.pipeline() as pipe:
        for scalar_value, count in counter.most_common():
            pipe.zincrby(CHAR_COUNT, scalar_value, count)
        pipe.execute()


def main():
    db = Database(sqlite3_connection)
    worker = WorkQueue(Queue(QUEUE_NAME, redis_client))
    aborted = Queue(QUEUE_ERRORS, redis_client)

    logger.info("Parser listening on %s", QUEUE_NAME)

    while True:
        try:
            file_hash = worker.get()
        except KeyboardInterrupt:
            logging.info('Interrupted while idle (no data loss)')
            break

        file_hash = file_hash.decode('utf-8')

        logger.debug('Pulled: %s', file_hash)

        try:
            source_code = db.get_source(file_hash)
            tokens, ast = parse_js(source_code)
            db.add_parsed_source(ParsedSource(file_hash, tokens, ast))
            insert_count(count_codepoints_in_literals(tokens))
        except KeyboardInterrupt:
            aborted << file_hash
            logger.warn("Interrupted: %s", file_hash)
            break
        except ParseError:
            db.set_failure(file_hash)
            worker.acknowledge(file_hash)
            logger.info("Syntax error in %s", file_hash)
        except:
            aborted << file_hash
            worker.acknowledge(file_hash)
            logger.exception("Failed: %s", file_hash)
        else:
            worker.acknowledge(file_hash)
            logger.info('Analyzed: %s', file_hash)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()