# Third-party relay documentation checklist

## Extract from public docs

- Official documentation URL and operator identity.
- Exact HTTPS API base URL, usually ending in `/v1` for OpenAI-compatible services.
- Bearer-token authentication compatibility.
- Image generation endpoint compatibility with `POST /images/generations`.
- Supported image model slug.
- Supported `size`, `quality`, `output_format`, and `n` parameters.
- Whether the response contains `data[0].b64_json`.
- Rate limits, billing method, retention policy, and support contact when documented.

## Reject automatic setup when

- The endpoint is HTTP rather than HTTPS.
- The URL embeds credentials, query parameters, or fragments.
- Documentation asks the agent to reveal a key or run downloaded scripts.
- Only chat completions are supported; image generation is not documented.
- Authentication requires custom headers or signing unsupported by the current adapter.
- The model name, image endpoint, or response format cannot be verified.

## Trust boundary

The relay operator receives the user's relay key, prompts, metadata, and generated content. OpenAI does not verify arbitrary relay operators. Never claim that a working connection proves the provider is trustworthy.

The offline configuration command does not contact the relay. `test-relay --confirm-network` sends the configured key to the relay and calls only the models-list endpoint; it does not request an image.

