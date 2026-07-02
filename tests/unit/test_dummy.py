# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
You can add your unit tests here.
This is where you test your business logic, including agent functionality,
data processing, and other core components of your application.
"""


def test_dummy() -> None:
    from app.agent import root_agent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.adk.agents.run_config import RunConfig, StreamingMode
    from google.genai import types

    session_service = InMemorySessionService()
    session = session_service.create_session_sync(user_id="test_user", app_name="test")
    runner = Runner(agent=root_agent, session_service=session_service, app_name="test")

    message = types.Content(
        role="user", parts=[types.Part.from_text(text="Why is the sky blue?")]
    )

    events = list(
        runner.run(
            new_message=message,
            user_id="test_user",
            session_id=session.id,
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        )
    )

    print("\n--- TEST AGENT STREAM EVENTS ---")
    print(f"Total events: {len(events)}")
    for i, event in enumerate(events):
        print(f"Event {i}: type={type(event)}, name={getattr(event, 'name', None)}")
        if hasattr(event, "content") and event.content:
            print(f"  content.role={event.content.role}")
            print(f"  content.parts={event.content.parts}")
        if hasattr(event, "output") and event.output:
            print(f"  output={event.output}")
    print("--------------------------------\n")
    assert 1 == 1

