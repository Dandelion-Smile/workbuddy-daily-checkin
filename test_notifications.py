from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import mail_notifications as mail
import workbuddy_checkin as checkin


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)
        self.config = json.loads((ROOT / 'config.example.json').read_text(encoding='utf-8'))
        self.config['runtime_directory'] = str(self.runtime)
        self.config['account_menu_name'] = 'TestAccount'
        self.config['email_notification']['sender'] = 'test-sender@qq.com'
        self.config['email_notification']['recipient'] = 'test-recipient@qq.com'
        self.config['email_notification']['enabled'] = True
        self.day = date.today().isoformat()

    @patch.object(mail, 'read_authorization_code', return_value='fake-test-secret')
    @patch.object(mail, 'send_message')
    def test_confirmed_reward_sends_once_with_exact_body(self, send, credential):
        self.assertEqual(mail.notify_success(self.config, self.runtime, self.day, 'claimed'), 'sent')
        self.assertEqual(mail.notify_success(self.config, self.runtime, self.day, 'already_claimed'), 'already_sent')
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0]['recipient'], 'test-recipient@qq.com')
        self.assertEqual(send.call_args.args[2], '今日的workbuddyy积分已经领取')
        credential.assert_called_once()

    @patch.object(mail, 'read_authorization_code', return_value='fake-test-secret')
    @patch.object(mail, 'send_message', side_effect=[mail.MailSendError('test failure'), None])
    def test_failed_email_is_retried_without_success_marker(self, send, credential):
        with self.assertRaises(mail.MailSendError):
            mail.notify_success(self.config, self.runtime, self.day, 'claimed')
        self.assertFalse((self.runtime / 'mail-success.json').exists())
        self.assertEqual(mail.notify_success(self.config, self.runtime, self.day, 'claimed'), 'sent')
        self.assertEqual(send.call_count, 2)

    @patch.object(mail, 'read_authorization_code')
    def test_disabled_email_needs_no_credentials(self, credential):
        self.config['email_notification']['enabled'] = False
        self.assertEqual(mail.notify_success(self.config, self.runtime, self.day, 'claimed'), 'disabled')
        credential.assert_not_called()

    @patch.object(mail, 'read_authorization_code')
    def test_failed_or_old_checkin_cannot_send_success_email(self, credential):
        with self.assertRaises(ValueError):
            mail.notify_success(self.config, self.runtime, self.day, 'failed')
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.assertEqual(mail.notify_success(self.config, self.runtime, yesterday, 'claimed'), 'stale')
        credential.assert_not_called()

    @patch.object(mail, 'read_authorization_code', return_value='fake-test-secret')
    @patch.object(mail, 'send_message')
    def test_previous_day_does_not_suppress_today(self, send, credential):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        (self.runtime / 'mail-success.json').write_text(json.dumps({'date': yesterday}), encoding='utf-8')
        self.assertEqual(mail.notify_success(self.config, self.runtime, self.day, 'already_claimed'), 'sent')
        send.assert_called_once()

    @patch.object(mail.smtplib, 'SMTP_SSL')
    def test_tls_mime_body_and_close_error_after_acceptance(self, factory):
        connection = factory.return_value
        connection.send_message.return_value = {}
        connection.close.side_effect = OSError('test socket close error')
        settings = mail.mail_settings(self.config)
        mail.send_message(settings, 'fake-test-secret', mail.NOTICE, 'test', 'test-key')
        kwargs = factory.call_args.kwargs
        self.assertTrue(kwargs['context'].check_hostname)
        self.assertEqual(factory.call_args.args, ('smtp.qq.com', 465))
        message = connection.send_message.call_args.args[0]
        self.assertEqual(message.get_content().strip(), '今日的workbuddyy积分已经领取')
        self.assertEqual(connection.send_message.call_args.kwargs['to_addrs'], ['test-recipient@qq.com'])

    @patch.object(mail.smtplib, 'SMTP_SSL')
    def test_authentication_error_does_not_reveal_secret(self, factory):
        factory.return_value.login.side_effect = RuntimeError('fake-secret-should-never-be-logged')
        with self.assertRaises(mail.MailSendError) as raised:
            mail.open_authenticated_connection(mail.mail_settings(self.config), 'fake-test-secret')
        self.assertNotIn('fake-secret', str(raised.exception))
        self.assertNotIn('fake-test-secret', str(raised.exception))

    def test_checkin_persisted_before_mail_failure_and_cached_retry_avoids_app(self):
        exe = Path('C:/test/WorkBuddy.exe')
        kernel = Mock()
        kernel.CreateMutexW.return_value = 1
        fixed_now = datetime.now().replace(hour=12)
        with (patch.object(checkin, 'load_config', return_value=(self.config, exe)),
              patch.object(checkin, 'configure_logging'),
              patch.object(checkin.ctypes, 'WinDLL', return_value=kernel),
              patch.object(checkin.ctypes, 'get_last_error', return_value=0),
              patch.object(checkin, 'datetime') as clock,
              patch.object(checkin, 'perform_checkin', return_value='claimed') as perform,
              patch.object(checkin, 'notify_success') as notify,
              patch.object(sys, 'argv', ['workbuddy_checkin.py', '--scheduled'])):
            clock.now.return_value = fixed_now
            def fail_after_persist(*args):
                saved = json.loads((self.runtime / 'last-success.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['status'], 'claimed')
                raise mail.MailSendError('simulated offline mail server')
            notify.side_effect = fail_after_persist
            self.assertEqual(checkin.main(), 75)
            self.assertEqual(checkin.main(), 75)
            self.assertEqual(perform.call_count, 1)
            self.assertEqual(notify.call_count, 2)
            notify.side_effect = None
            self.assertEqual(checkin.main(), 0)
            self.assertEqual(perform.call_count, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
