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

import os
# Force GOOGLE_GENAI_USE_VERTEXAI to False to use the Developer API key and AI Studio endpoints
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"

from unittest.mock import MagicMock
import google.auth
import google.cloud.logging
import vertexai
import google.cloud.aiplatform.utils.resource_manager_utils as rm_utils
from vertexai.agent_engines.templates.adk import AdkApp

class DummyCredentials:
    def __init__(self):
        self.quota_project_id = "dummy-project"
        self.token = "dummy-token"
        self.expired = False
        self.valid = True

    def refresh(self, request):
        pass

    def before_request(self, request, method, url, headers):
        headers["Authorization"] = f"Bearer {self.token}"
        if self.quota_project_id:
            headers["x-goog-user-project"] = self.quota_project_id

# Mock google.auth.default to return our dummy credentials
google.auth.default = MagicMock(return_value=(DummyCredentials(), "dummy-project"))

# Mock google.cloud.logging.Client to avoid connecting to Google Cloud
google.cloud.logging.Client = MagicMock()

# Mock vertexai.init
vertexai.init = MagicMock()

# Mock get_project_id to avoid calling the ResourceManager API
rm_utils.get_project_id = MagicMock(side_effect=lambda project: project)

# Patch AdkApp.set_up to override GOOGLE_GENAI_USE_VERTEXAI back to False after setup
original_set_up = AdkApp.set_up
def mocked_set_up(self, *args, **kwargs):
    res = original_set_up(self, *args, **kwargs)
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"
    return res

AdkApp.set_up = mocked_set_up
