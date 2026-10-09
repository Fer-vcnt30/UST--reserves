import io
import unittest
from unittest.mock import patch, Mock
import app as module

class StartupTests(unittest.TestCase):
    def call(self, method='GET'):
        response = {}
        def start(status, headers):
            response.update(status=status, headers=dict(headers))
        response['body'] = b''.join(module.app({'PATH_INFO':'/', 'REQUEST_METHOD':method, 'wsgi.input':io.BytesIO()}, start))
        return response

    def test_render_origin_fallback(self):
        self.assertEqual(module.production_origin({'RENDER_EXTERNAL_URL':'https://test.onrender.com','DATABASE_URL':'configured'}),'https://test.onrender.com')

    def test_explicit_netlify_origin_has_priority(self):
        self.assertEqual(module.production_origin({'APP_ORIGIN':'https://reservaust.netlify.app/','RENDER_EXTERNAL_URL':'https://test.onrender.com','DATABASE_URL':'configured'}),'https://reservaust.netlify.app')

    def test_missing_configuration_identifies_variable_not_secret(self):
        with self.assertRaisesRegex(module.StartupConfigurationError, 'DATABASE_URL'):
            module.production_origin({'APP_ORIGIN':'https://example.com'})

    def test_bad_origin_rejected(self):
        for value in ['http://example.com', 'https:///missing', 'https://user:secret@example.com', 'https://example.com/path', 'https://example.com?x=y']:
            with self.assertRaises(module.StartupConfigurationError):
                module.production_origin({'APP_ORIGIN':value,'DATABASE_URL':'configured'})

    def test_missing_config_returns_503_instead_of_uncaught_exception(self):
        with patch.object(module, '_application', None), patch.dict(module.os.environ, {}, clear=True):
            result = self.call()
            self.assertTrue(result['status'].startswith('503'))
            self.assertEqual(result['headers']['Cache-Control'], 'no-store')
            self.assertIn(b'APP_ORIGIN', result['body'])

    def test_head_startup_failure_has_no_body(self):
        with patch.object(module, '_application', None), patch.dict(module.os.environ, {}, clear=True):
            result = self.call('HEAD')
            self.assertTrue(result['status'].startswith('503'))
            self.assertEqual(result['body'], b'')

    def test_database_failure_does_not_disclose_connection(self):
        with patch.object(module, '_application', None), patch.dict(module.os.environ, {'APP_ORIGIN':'https://example.com','DATABASE_URL':'private-secret'}, clear=True), patch.object(module,'Database',side_effect=Exception('private-secret')):
            result = self.call()
            self.assertTrue(result['status'].startswith('503'))
            self.assertNotIn(b'private-secret', result['body'])

    def test_failed_startup_can_recover_after_configuration(self):
        database = Mock()
        application = Mock(return_value=[b'ready'])
        with patch.object(module, '_application', None), patch.dict(module.os.environ, {}, clear=True), patch.object(module, 'Database', return_value=database), patch.object(module, 'Service'), patch.object(module, 'Application', return_value=application):
            self.assertTrue(self.call()['status'].startswith('503'))
            module.os.environ.update(APP_ORIGIN='https://example.com',DATABASE_URL='configured')
            self.assertEqual(self.call()['body'], b'ready')
            database.initialize.assert_called_once()

if __name__ == '__main__':
    unittest.main()
