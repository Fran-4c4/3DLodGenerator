# Offline CityJSON validation schema

`cityjson-2.0.1.schema.json` is the official self-contained/minified CityJSON
2.0.1 schema, included for offline acceptance tests. Preserve its CC0 licence
in [LICENSE-CityJSON.txt](LICENSE-CityJSON.txt).

Source: [CityJSON specifications, tag 2.0.1](https://github.com/cityjson/specs/blob/2.0.1/schemas/cityjson.min.schema.json).
SHA-256: `2c562421af9c91da716e55551e1581c3a192430e2556e66d077a1e2ad1cb804a`.

Schema version 2.0.1 validates models with `version: "2.0"`, as specified.
jsonschema checks structure/fields; shell, volume and courtyard tests provide
separate geometric evidence. Do not dump the schema to logs: it is a large
single-line JSON record.
