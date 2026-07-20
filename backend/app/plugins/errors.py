class PluginError(Exception):
    """Base exception for plugin operations."""


class PluginNotFoundError(PluginError):
    pass


class PluginValidationError(PluginError):
    pass
