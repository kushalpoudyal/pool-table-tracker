"""BifrostWriter against a stand-in for the OpenAI SDK pointed at the gateway: what is sent, what comes back."""
import unittest
from types import SimpleNamespace as NS

from app import commentator
from app.commentator import PERSONA, BifrostWriter, Request


class Stream:
    def __init__(self, texts, finish="stop", clock=None, step=0.0):
        self.texts, self.finish, self.clock, self.step, self.closed = texts, finish, clock, step, False

    def __iter__(self):
        for i, t in enumerate(self.texts):
            if self.clock:
                self.clock.now += self.step
            last = i == len(self.texts) - 1
            yield NS(choices=[NS(delta=NS(content=t), finish_reason=self.finish if last else None)], usage=None)
        yield NS(choices=[], usage=NS(prompt_tokens=400, completion_tokens=30))

    def close(self):
        self.closed = True


class Client:
    def __init__(self, stream=None, error=None):
        self.stream, self.error, self.sent, self.options = stream, error, None, None
        self.chat = NS(completions=NS(create=self.create))

    def with_options(self, **options):
        self.options = options
        return self

    def create(self, **kwargs):
        self.sent = kwargs
        if self.error:
            raise self.error
        return self.stream


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def ask(client, clock=None):
    got = []
    writer = BifrostWriter(client, spawn=lambda work, *args: work(*args), clock=clock or Clock())
    writer.ask(Request("shot", writer.model, PERSONA, {"x": 1}), got.append)
    return got[0], writer


class BifrostWriterTest(unittest.TestCase):
    def test_a_fast_model_streamed_with_reasoning_off_and_no_retries(self):
        client = Client(Stream(["A tidy ", "start."]))
        line, writer = ask(client)
        self.assertEqual(line, "A tidy start.")
        self.assertEqual(client.sent["model"], "openai/gpt-6-luna")
        self.assertEqual(client.sent["reasoning_effort"], "none")
        self.assertTrue(client.sent["stream"])
        self.assertEqual(client.sent["messages"][0], {"role": "system", "content": PERSONA})
        self.assertIn('"x": 1', client.sent["messages"][1]["content"])
        self.assertEqual(client.options, {"timeout": 5.0, "max_retries": 0})
        self.assertEqual(writer.usage, {"input_tokens": 400, "output_tokens": 30, "requests": 1})

    def test_cut_short_keeps_whole_sentences(self):
        self.assertEqual(ask(Client(Stream(["One. Two and"], "length")))[0], "One.")

    def test_too_slow_is_given_up_and_the_stream_closed(self):
        clock = Clock()
        stream = Stream(["a ", "b ", "c."], clock=clock, step=3)
        self.assertIsNone(ask(Client(stream), clock)[0])
        self.assertTrue(stream.closed)

    def test_an_error_is_no_line(self):
        self.assertIsNone(ask(Client(error=ConnectionError("down")))[0])

    def test_settings(self):
        c = commentator.from_env({"BIFROST_URL": "gateway.example", "BIFROST_API_KEY": "k", "ANTHROPIC_API_KEY": "a"})
        self.assertIsInstance(c.writer, BifrostWriter)  # the gateway first
        self.assertEqual(str(c.writer._client.base_url), "https://gateway.example/v1/")
        c = commentator.from_env({"BIFROST_URL": "https://gateway.example/v1", "BIFROST_API_KEY": "k",
                                  "COMMENTARY_MODEL": "openai/gpt-6.2-astra"})
        self.assertEqual((str(c.writer._client.base_url), c.writer.model), ("https://gateway.example/v1/", "openai/gpt-6.2-astra"))
        self.assertIsInstance(commentator.from_env({"ANTHROPIC_API_KEY": "a"}).writer, commentator.ClaudeWriter)


if __name__ == "__main__":
    unittest.main()
