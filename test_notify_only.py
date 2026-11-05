"""Mail catch-up checks. All SMTP, process creation and desktop actions are mocked."""
from datetime import date, datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import mail_notifications as mail
import setup_email
import workbuddy_checkin as checkin


class NotifyOnlyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.runtime = Path(temporary.name)
        self.exe = Path('C:/test/WorkBuddy.exe')
        self.config = {
            'workbuddy_exe': str(self.exe), 'account_menu_name': 'TestAccount',
            'runtime_directory': str(self.runtime),
            'email_notification': {'enabled': True, 'smtp_host': 'smtp.qq.com', 'smtp_port': 465,
                                   'sender': 'test-sender@qq.com', 'recipient': 'test-recipient@qq.com'},
        }

    def save_confirmed(self, status='already_claimed'):
        record = {'date': date.today().isoformat(), 'status': status,
                  'account_menu_name': self.config['account_menu_name'], 'exe': str(self.exe)}
        (self.runtime / 'last-success.json').write_text(json.dumps(record), encoding='utf-8')

    def run_notification(self, notify_failure=None):
        kernel = Mock()
        kernel.CreateMutexW.return_value = 1
        with (patch.object(checkin, 'load_config', return_value=(self.config, self.exe)),
              patch.object(checkin, 'configure_logging'),
              patch.object(checkin.ctypes, 'WinDLL', return_value=kernel),
              patch.object(checkin.ctypes, 'get_last_error', return_value=0),
              patch.object(checkin, 'perform_checkin') as app_action,
              patch.object(checkin, 'get_or_launch_window') as launch,
              patch.object(checkin, 'notify_success', side_effect=notify_failure, return_value='sent') as notify,
              patch.object(sys, 'argv', ['workbuddy_checkin.py', '--notify-only'])):
            exit_code = checkin.main()
            app_action.assert_not_called()
            launch.assert_not_called()
            return exit_code, notify

    def test_already_claimed_catches_up_without_opening_workbuddy(self):
        self.save_confirmed()
        code, notify = self.run_notification()
        self.assertEqual(code, 0)
        self.assertEqual(notify.call_args.args[-1], 'already_claimed')

    def test_claimed_result_also_catches_up(self):
        self.save_confirmed('claimed')
        code, notify = self.run_notification()
        self.assertEqual(code, 0)
        self.assertEqual(notify.call_args.args[-1], 'claimed')

    def test_no_verified_result_cannot_send_success_email(self):
        code, notify = self.run_notification()
        self.assertEqual(code, 75)
        notify.assert_not_called()

    def test_disabled_notification_is_explicit_failure_for_mail_only(self):
        self.save_confirmed()
        self.config['email_notification']['enabled'] = False
        code, notify = self.run_notification()
        self.assertEqual(code, 75)
        notify.assert_not_called()

    def test_mail_failure_keeps_confirmed_checkin_for_retry(self):
        self.save_confirmed()
        before = (self.runtime / 'last-success.json').read_bytes()
        code, _ = self.run_notification(mail.MailSendError('simulated SMTP failure'))
        self.assertEqual(code, 75)
        self.assertEqual((self.runtime / 'last-success.json').read_bytes(), before)

    @patch.object(setup_email.subprocess, 'run', return_value=Mock(returncode=0))
    def test_email_setup_immediately_submits_existing_today_result(self, run):
        self.save_confirmed()
        setup_email.notify_confirmed_today(self.config)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][-1], '--notify-only')

    @patch.object(setup_email.subprocess, 'run')
    def test_email_setup_does_not_invent_a_claim(self, run):
        setup_email.notify_confirmed_today(self.config)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
