import json
import logging
import os
from unittest import mock

import coverage
import pytest
import requests

from coveralls import Coveralls
from coveralls.api import log as api_log
from coveralls.exception import CoverallsException


@mock.patch.dict(os.environ, {}, clear=True)
def test_output_to_file(tmpdir):
    """Check we can write coveralls report into the file."""
    test_log = tmpdir.join('test.log')
    Coveralls(repo_token='xxx').save_report(test_log.strpath)
    report = test_log.read()

    assert json.loads(report)['repo_token'] == 'xxx'

@mock.patch('coveralls.api.requests.post')
def test_submit_report_warns_for_github_422(mock_post, capsys):
    cover = Coveralls(token_required=False)
    cover.config['service_name'] = 'github-actions'

    response = mock.Mock()
    response.status_code = 422
    response.raise_for_status.return_value = None
    response.json.return_value = {'status': 'ok'}
    mock_post.return_value = response

    cover.submit_report('{}')

    captured = capsys.readouterr()
    assert 'Received 422 submitting job via Github Actions' in captured.out


@mock.patch('coveralls.api.requests.post')
def test_parallel_finish_raises_when_request_fails(mock_post):
    cover = Coveralls(token_required=False)

    response = mock.Mock()
    response.raise_for_status.side_effect = requests.HTTPError('nope')
    mock_post.return_value = response

    with pytest.raises(CoverallsException, match='Parallel finish failed: nope'):
        cover.parallel_finish()


@mock.patch.object(Coveralls, 'create_data', return_value={'source_files': []})
def test_create_report_handles_unicode_error(mock_create_data):
    cover = Coveralls(token_required=False)

    def boom(*_args, **_kwargs):  # noqa: ANN001
        raise UnicodeDecodeError('utf-8', b'bad', 0, 1, 'boom')

    with mock.patch.object(Coveralls, 'debug_bad_encoding') as mock_debug:
        with mock.patch('coveralls.api.json.dumps', side_effect=boom):
            with pytest.raises(UnicodeDecodeError):
                cover.create_report()

    mock_debug.assert_called_once_with(mock_create_data.return_value)


def test_save_report_logs_on_coverage_exception(tmp_path):
    cover = Coveralls(token_required=False)
    target = tmp_path / 'report.json'

    with mock.patch.object(Coveralls, 'create_report', side_effect=coverage.CoverageException('no data')):
        with mock.patch.object(api_log, 'exception') as mock_log:
            cover.save_report(str(target))

    mock_log.assert_called_once_with('Failure to gather coverage:')
    assert not target.exists()


def test_debug_bad_encoding_logs_offending_files(caplog):
    caplog.set_level(logging.ERROR)
    data = {'source_files': [{'name': 'bad.py', 'bad_value': 'trigger'}]}

    real_dumps = json.dumps

    def fake_dumps(value, *args, **kwargs):  # noqa: ANN001
        if value == 'trigger':
            raise UnicodeDecodeError('utf-8', b'bad', 0, 1, 'boom')
        return real_dumps(value, *args, **kwargs)

    with mock.patch('coveralls.api.json.dumps', side_effect=fake_dumps):
        Coveralls.debug_bad_encoding(data)

    assert 'bad.py' in caplog.text

