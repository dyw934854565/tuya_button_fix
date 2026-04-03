DOMAIN = "tuya_button_fix"
EVENT_TYPE = "tuya_button_click"
SUPPORTED_ATTRS = ("switch_mode1", "switch_mode", "switch_mode_1")
VALUE_MAP = {
    "click": "single",
    "single_click": "single",
    "double": "double",
    "double_click": "double",
    "press": "long",
    "long_press": "long",
}
