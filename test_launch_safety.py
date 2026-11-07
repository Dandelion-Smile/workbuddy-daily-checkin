"""Regression checks using fake windows/processes; no desktop input is sent."""
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import workbuddy_checkin as checkin


class LaunchSafetyTests(unittest.TestCase):
    def setUp(self):
        self.exe = Path('C:/test/WorkBuddy.exe')

    def test_orphaned_sidecar_and_worker_are_not_the_main_application(self):
        inventory = [
            {'pid': 10, 'parent': 9, 'command': 'WorkBuddy.exe "C:/app/main/sidecar-entry.js"'},
            {'pid': 11, 'parent': 10, 'command': 'WorkBuddy.exe service-worker'},
        ]
        self.assertFalse(checkin.has_main_process(inventory))

    def test_starting_main_process_blocks_duplicate_launch_without_window(self):
        inventory = [
            {'pid': 10, 'parent': 1, 'command': 'WorkBuddy.exe'},
            {'pid': 11, 'parent': 10, 'command': 'WorkBuddy.exe --type=gpu-process'},
        ]
        self.assertTrue(checkin.has_main_process(inventory))

    def test_existing_window_never_starts_a_second_process(self):
        window = Mock()
        with (patch.object(checkin, 'find_window', return_value=window),
              patch.object(checkin, 'workbuddy_running') as running,
              patch.object(checkin, 'launch_workbuddy') as launch):
            self.assertIs(checkin.get_or_launch_window(self.exe), window)
            running.assert_not_called()
            launch.assert_not_called()

    def test_running_without_window_stops_without_launch(self):
        with (patch.object(checkin, 'find_window', return_value=None),
              patch.object(checkin, 'workbuddy_running', return_value=True),
              patch.object(checkin, 'launch_workbuddy') as launch):
            with self.assertRaisesRegex(RuntimeError, 'No second copy started'):
                checkin.get_or_launch_window(self.exe, timeout=60)
            launch.assert_not_called()

    def test_not_running_launches_once_and_waits_for_window(self):
        window = Mock()
        with (patch.object(checkin, 'find_window', side_effect=[None, None, window]),
              patch.object(checkin, 'workbuddy_running', return_value=False),
              patch.object(checkin, 'launch_workbuddy') as launch,
              patch.object(checkin.time, 'sleep')):
            self.assertIs(checkin.get_or_launch_window(self.exe), window)
            launch.assert_called_once()

    def test_startup_timeout_never_relaunches(self):
        with (patch.object(checkin, 'find_window', return_value=None),
              patch.object(checkin, 'workbuddy_running', return_value=False),
              patch.object(checkin, 'launch_workbuddy') as launch,
              patch.object(checkin.time, 'monotonic', side_effect=[0, 1, 100]),
              patch.object(checkin.time, 'sleep')):
            with self.assertRaisesRegex(RuntimeError, 'no additional copy started'):
                checkin.get_or_launch_window(self.exe, timeout=60)
            launch.assert_called_once()

    def test_hidden_native_window_is_restored_before_uia_binding(self):
        window = Mock()
        with (patch.object(checkin, 'native_window_handles', return_value=[123]),
              patch('win32gui.IsWindowVisible', return_value=False),
              patch('win32gui.IsIconic', return_value=False),
              patch('win32gui.ShowWindow') as restore,
              patch('pywinauto.Desktop') as desktop):
            desktop.return_value.window.return_value.wrapper_object.return_value = window
            self.assertIs(checkin.find_window(self.exe), window)
            restore.assert_called_once()
            desktop.return_value.window.assert_called_once_with(handle=123)

    def test_ready_wait_rebinds_after_splash_is_replaced(self):
        splash, main, card = Mock(), Mock(), Mock()
        with (patch.object(checkin, 'find_window', side_effect=[splash, main]),
              patch.object(checkin, 'account_card', side_effect=[None, card]),
              patch.object(checkin, 'profile_controls', return_value=[]),
              patch.object(checkin.time, 'sleep')):
            actual, actual_card, profiles = checkin.wait_account_ready(splash, {}, exe=self.exe)
            self.assertIs(actual, main)
            self.assertIs(actual_card, card)

    def test_confirmation_reopens_closed_menu_without_claiming_twice(self):
        window, card, claimed_card, profile = Mock(), Mock(), Mock(), Mock()
        button = Mock()
        button.element_info.name = '立即领取'
        config = {'claim_button_labels': ['立即领取']}
        with (patch.object(checkin, 'desktop_unlocked', return_value=True),
              patch.object(checkin, 'get_or_launch_window', return_value=window),
              patch.object(checkin, 'focus_window'),
              patch.object(checkin, 'wait_account_ready', return_value=(window, None, [profile])),
              patch.object(checkin, 'wait_card', return_value=card),
              patch.object(checkin, 'claimed', side_effect=[False, True]),
              patch.object(checkin, 'visible_buttons', return_value=[button]),
              patch.object(checkin, 'account_card', side_effect=[None, claimed_card]),
              patch.object(checkin, 'profile_controls', return_value=[profile]),
              patch.object(checkin, 'activate_control') as act,
              patch.object(checkin.time, 'sleep')):
            self.assertEqual(checkin.perform_checkin(config, self.exe), 'claimed')
            self.assertEqual([entry.args[0] for entry in act.call_args_list], [profile, button, profile])

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

    def test_covered_control_does_not_click_another_window(self):
        control = Mock()
        control.rectangle.return_value.mid_point.return_value = Mock(x=10, y=20)
        hit = Mock()
        hit.parent.return_value = None
        with (patch.object(checkin, 'desktop_unlocked', return_value=True),
              patch.object(checkin, 'ensure_foreground'),
              patch('pywinauto.Desktop') as desktop):
            desktop.return_value.from_point.return_value = hit
            with self.assertRaisesRegex(RuntimeError, 'covered or stale'):
                checkin.activate_control(control)
            control.click_input.assert_not_called()

    def test_click_requires_hit_test_to_match_the_current_control(self):
        control = Mock()
        control.rectangle.return_value.mid_point.return_value = Mock(x=10, y=20)
        child = Mock()
        child.parent.return_value = control
        with (patch.object(checkin, 'desktop_unlocked', return_value=True),
              patch.object(checkin, 'ensure_foreground'),
              patch('pywinauto.Desktop') as desktop):
            desktop.return_value.from_point.return_value = child
            checkin.activate_control(control)
            control.click_input.assert_called_once_with(use_log=False)

    def test_disabled_control_is_not_clicked(self):
        control = Mock()
        control.is_enabled.return_value = False
        with (patch.object(checkin, 'desktop_unlocked', return_value=True),
              patch.object(checkin, 'ensure_foreground')):
            with self.assertRaisesRegex(RuntimeError, 'disabled'):
                checkin.activate_control(control)
            control.click_input.assert_not_called()

    def test_failed_foreground_activation_is_explicit(self):
        window = Mock(handle=123)
        window.process_id.return_value = 20
        with (patch('win32gui.GetForegroundWindow', return_value=999),
              patch('win32process.GetWindowThreadProcessId', return_value=(1, 30)),
              patch('pywinauto.controls.hwndwrapper.HwndWrapper')):
            with self.assertRaisesRegex(RuntimeError, 'no click sent'):
                checkin.ensure_foreground(window)


if __name__ == '__main__':
    unittest.main(verbosity=2)
