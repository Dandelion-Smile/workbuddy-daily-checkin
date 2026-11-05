"""Regression checks using fake windows/processes; no desktop input is sent."""
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import workbuddy_checkin as checkin


class LaunchSafetyTests(unittest.TestCase):
    def setUp(self):
        self.exe = Path('C:/test/WorkBuddy.exe')

    def test_existing_window_never_starts_a_second_process(self):
        window = Mock()
        with (patch.object(checkin, 'find_window', return_value=window),
              patch.object(checkin, 'workbuddy_running') as running,
              patch.object(checkin.subprocess, 'Popen') as launch):
            self.assertIs(checkin.get_or_launch_window(self.exe), window)
            running.assert_not_called()
            launch.assert_not_called()

    def test_running_without_window_stops_without_launch(self):
        with (patch.object(checkin, 'find_window', return_value=None),
              patch.object(checkin, 'workbuddy_running', return_value=True),
              patch.object(checkin.subprocess, 'Popen') as launch):
            with self.assertRaisesRegex(RuntimeError, 'No second copy started'):
                checkin.get_or_launch_window(self.exe)
            launch.assert_not_called()

    def test_not_running_launches_once_and_waits_for_window(self):
        window = Mock()
        with (patch.object(checkin, 'find_window', side_effect=[None, None, window]),
              patch.object(checkin, 'workbuddy_running', return_value=False),
              patch.object(checkin.subprocess, 'Popen') as launch,
              patch.object(checkin.time, 'sleep')):
            self.assertIs(checkin.get_or_launch_window(self.exe), window)
            launch.assert_called_once()

    def test_startup_timeout_never_relaunches(self):
        with (patch.object(checkin, 'find_window', return_value=None),
              patch.object(checkin, 'workbuddy_running', return_value=False),
              patch.object(checkin.subprocess, 'Popen') as launch,
              patch.object(checkin.time, 'monotonic', side_effect=[0, 1, 100]),
              patch.object(checkin.time, 'sleep')):
            with self.assertRaisesRegex(RuntimeError, 'no additional copy started'):
                checkin.get_or_launch_window(self.exe)
            launch.assert_called_once()

    def test_blank_interface_waits_then_stops_without_action(self):
        with (patch.object(checkin, 'account_card', return_value=None),
              patch.object(checkin, 'profile_controls', return_value=[]),
              patch.object(checkin.time, 'monotonic', side_effect=[0, 1, 100]),
              patch.object(checkin.time, 'sleep'),
              patch.object(checkin, 'activate_control') as click):
            with self.assertRaisesRegex(RuntimeError, 'not ready'):
                checkin.wait_account_ready(Mock(), {})
            click.assert_not_called()

    def test_minimized_pane_restores_without_uia_window_pattern(self):
        window = Mock(handle=123)
        with (patch('win32gui.IsIconic', return_value=True),
              patch('win32gui.ShowWindow') as restore,
              patch('win32gui.SetForegroundWindow') as activate):
            checkin.focus_window(window)
            restore.assert_called_once()
            activate.assert_called_once_with(123)
            window.set_focus.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
