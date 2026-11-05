"""Credential compatibility regression checks. Uses fake authorization only."""
import json
import os
from pathlib import Path
import smtplib
import tempfile
import unittest
from unittest.mock import Mock, patch

import win32cred
import mail_notifications as mail
import setup_email


class CredentialTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.config = {'account_menu_name': 'TestAccount', 'workbuddy_exe': 'C:/test/WorkBuddy.exe',
                       'runtime_directory': str(self.base),
                       'email_notification': {'enabled': False, 'sender': 'test-sender@qq.com',
                                              'recipient': 'test-recipient@qq.com',
                                              'smtp_host': 'smtp.qq.com', 'smtp_port': 465}}
        (self.base / 'config.json').write_text(json.dumps(self.config), encoding='utf-8')
        self.fake_code = 'abcdefghijklmnop'

    def test_save_passes_text_to_windows_and_enables_after_success(self):
        with (patch.object(setup_email, 'BASE', self.base),
              patch.object(setup_email, 'open_authenticated_connection', return_value=Mock()),
              patch.object(win32cred, 'CredWrite') as write):
            configured = setup_email.configure_authorization('abcd efgh ijkl mnop')
            blob = write.call_args.args[0]['CredentialBlob']
            self.assertIsInstance(blob, str)
            self.assertEqual(blob, self.fake_code)
            self.assertTrue(configured['email_notification']['enabled'])
            self.assertNotIn(self.fake_code, (self.base / 'config.json').read_text(encoding='utf-8'))

    def test_failed_windows_write_does_not_enable_notifications(self):
        with (patch.object(setup_email, 'BASE', self.base),
              patch.object(setup_email, 'open_authenticated_connection', return_value=Mock()),
              patch.object(win32cred, 'CredWrite', side_effect=TypeError('simulated write error'))):
            with self.assertRaises(TypeError):
                setup_email.configure_authorization(self.fake_code)
        configured = json.loads((self.base / 'config.json').read_text(encoding='utf-8'))
        self.assertFalse(configured['email_notification']['enabled'])

    def test_reads_windows_utf16_blob(self):
        saved = {'UserName': 'test-sender@qq.com', 'CredentialBlob': self.fake_code.encode('utf-16-le')}
        with patch.object(win32cred, 'CredRead', return_value=saved):
            self.assertEqual(mail.read_authorization_code(self.config['email_notification']), self.fake_code)

    def test_reads_legacy_utf8_blob(self):
        saved = {'UserName': 'test-sender@qq.com', 'CredentialBlob': self.fake_code.encode('utf-8')}
        with patch.object(win32cred, 'CredRead', return_value=saved):
            self.assertEqual(mail.read_authorization_code(self.config['email_notification']), self.fake_code)

    def test_error_report_does_not_persist_raw_exception_or_code(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': str(self.base)}):
            error = TypeError('private value: ' + self.fake_code)
            setup_email.record_setup_failure(error)
            message = setup_email.setup_error_message(error)
        log = (self.base / 'WorkBuddyDailyAutomation' / 'email-setup.log').read_text(encoding='utf-8')
        self.assertIn('TypeError', log)
        self.assertNotIn(self.fake_code, log + message)

    def test_smtp_rejection_exposes_status_not_raw_server_response(self):
        with patch.object(mail.smtplib, 'SMTP_SSL') as factory:
            factory.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, self.fake_code.encode())
            with self.assertRaises(mail.MailSendError) as raised:
                mail.open_authenticated_connection(self.config['email_notification'], self.fake_code)
        self.assertIn('535', str(raised.exception))
        self.assertNotIn(self.fake_code, str(raised.exception))


if __name__ == '__main__':
    unittest.main(verbosity=2)
