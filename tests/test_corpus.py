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

import datetime
from pathlib import PurePosixPath

import pytest  # type: ignore
from sqlalchemy import create_engine  # type: ignore
from sqlalchemy.sql import select  # type: ignore

# This is the WRONG place to store the WordCount class!
from sensibility.language import SourceSummary
from sensibility.miner.corpus import Corpus
from sensibility.miner.models import (
    RepositoryMetadata, SourceFile,
    SourceFileInRepository
)


def test_create(engine):
    db = empty_corpus()


def test_insert_source_summary(empty_corpus, repo_file) -> None:
    repository, _, _ = repo_file
    empty_corpus.insert_repository(repository)
    empty_corpus.insert_source_file_from_repo(repo_file)
    empty_corpus.insert_source_summary(repo_file.filehash,
                                       SourceSummary(2, 3))


def test_insert_and_retrieve(corpus, source_file):
    source_code = corpus.get_source(source_file.filehash)
    assert source_code == source_file.source
    assert SourceFile(source_code).filehash == source_file.filehash
    # Ensure we can the item back from the empty_corpus.
    assert corpus[source_file.filehash] == source_file.source


def test_metadata(corpus) -> None:
    assert corpus.language == 'Python'


def test_insert_duplicate(corpus: Corpus,
                          repo_file: SourceFileInRepository) -> None:
    """
    Insert the same file with two DIFFERENT paths.
    """
    with pytest.raises(Exception):
        corpus.insert_source_file_from_repo(repo_file)

    # Insert the SAME file, under a different path.
    repo_file2 = SourceFileInRepository(
        repository=repo_file.repository,
        source_file=repo_file.source_file,
        path=PurePosixPath('world.py')
    )

    # This should work:
    corpus.insert_source_file_from_repo(repo_file2)


################################## Fixtures ##################################

@pytest.fixture
def source_file() -> SourceFile:
    return SourceFile(
        source=b'import sys\n\nprint("hello, world")\n'
    )


@pytest.fixture
def repo_file() -> SourceFileInRepository:
    return SourceFileInRepository(
        repository=repository(),
        source_file=source_file(),
        path=PurePosixPath('hello.py')
    )


@pytest.fixture
def repository() -> RepositoryMetadata:
    return RepositoryMetadata(
        owner='owner', name='name',
        revision='01b474d88e84cf745ab1d96405fd48279fcb5a11',
        license='mit',
        commit_date=datetime.datetime.utcnow()
    )


@pytest.fixture
def corpus() -> Corpus:
    db = empty_corpus()
    db.set_metadata(language='Python',
                    started=datetime.datetime.utcnow())
    entry = repo_file()
    db.insert_repository(entry.repository)
    db.insert_source_file_from_repo(entry)
    return db


@pytest.fixture
def empty_corpus() -> Corpus:
    return Corpus(engine=engine())


@pytest.fixture
def engine():
    return create_engine('sqlite://', echo=True)
