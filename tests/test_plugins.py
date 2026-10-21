from jarvis_bot.config import Settings
from jarvis_bot.plugins import Plugin, PluginContext, PluginRegistry


def _settings() -> Settings:
    return Settings(TELEGRAM_BOT_TOKEN="123:abc", OPENROUTER_API_KEY="sk-test")


def test_registry_collects_tools_and_instructions() -> None:
    registry = PluginRegistry()

    def factory(context: PluginContext) -> Plugin:
        def hello(name: str = "") -> str:
            """Saluta."""
            return f"ciao {name}"

        return Plugin(name="demo", tools=[hello], instructions=["Istruzione demo."])

    registry.register("demo", factory)
    tools, instructions = registry.build(PluginContext(_settings(), 1))

    assert len(tools) == 1
    assert instructions == ["Istruzione demo."]
    assert registry.names() == ["demo"]


def test_broken_plugin_is_skipped() -> None:
    registry = PluginRegistry()
    registry.register("broken", lambda context: (_ for _ in ()).throw(RuntimeError("boom")))

    tools, instructions = registry.build(PluginContext(_settings(), 1))

    assert tools == []
    assert instructions == []
