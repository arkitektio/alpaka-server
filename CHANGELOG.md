# CHANGELOG


## v1.0.1 (2026-06-25)


## v1.0.1-rc.1 (2026-06-25)


## v1.0.0 (2026-06-25)


## v1.0.0-rc.2 (2026-06-25)

### Bug Fixes

- With historical message
  ([`f54507f`](https://github.com/arkitektio/alpaka-server/commit/f54507f83832143a63ddd36a3a5187d0a053d08e))


## v1.0.0-rc.1 (2026-06-25)

### Bug Fixes

- Add "contextual rooms"
  ([`1515bc7`](https://github.com/arkitektio/alpaka-server/commit/1515bc76abb36076081eb2f3e38f3bc651b77ece))

- Add unittests
  ([`5d019e9`](https://github.com/arkitektio/alpaka-server/commit/5d019e9b7bed0282e831f210b0eb1d488ac1e2b0))

- Alpaka
  ([`ccba9c4`](https://github.com/arkitektio/alpaka-server/commit/ccba9c40a5268ed9424e3c6126dec0c7a0d2aa03))

- Correct typo in CHROMA_DB_HOST configuration and format AUTHENTIKATE issuers
  ([`c0bbc8c`](https://github.com/arkitektio/alpaka-server/commit/c0bbc8c3c16937034efb0f0ecdcf1ddafbcd7031))

- Docker build
  ([`68f5f48`](https://github.com/arkitektio/alpaka-server/commit/68f5f48a381cdcdf9424e686b9698886f44005f6))

- Improve error handling and response processing in pull function
  ([`ba85e79`](https://github.com/arkitektio/alpaka-server/commit/ba85e791581d0f287380e1aaf2b258b88f7b2d1a))

- New filters
  ([`eff1b93`](https://github.com/arkitektio/alpaka-server/commit/eff1b9329da60a7a2ea1a2897ac04f979dbe605c))

- Room
  ([`3532b22`](https://github.com/arkitektio/alpaka-server/commit/3532b22197b6b7603ea46c1496a821b4d667faa6))

- Rooms
  ([`f59e5a3`](https://github.com/arkitektio/alpaka-server/commit/f59e5a330b334337862efd43c4e4d3737f2f0205))

- Update authentikate dependency to version 0.15
  ([`7a6ed51`](https://github.com/arkitektio/alpaka-server/commit/7a6ed512bd98e988975fa065c081108e717cf5ff))

- With filters
  ([`6e9bac9`](https://github.com/arkitektio/alpaka-server/commit/6e9bac9c39b0a0769f243c75c317f0f2513c2249))

### Features

- Add authentikate
  ([`114d342`](https://github.com/arkitektio/alpaka-server/commit/114d3426d35f388be6f052c299a531dac4c96a18))

- Add CHAT type to FeatureType enum
  ([`ca137e0`](https://github.com/arkitektio/alpaka-server/commit/ca137e0dfda5a44acb55c966bc8e2d65c3bd30dd))

- Add ChromaCollection model and related GraphQL mutations/queries
  ([`bc53c88`](https://github.com/arkitektio/alpaka-server/commit/bc53c88f82a741346a0c0daebee5647c70418603))

- Created ChromaCollection model with fields for name, description, created_at, owner, and embedder.
  - Implemented GraphQL mutations for creating, deleting, and ensuring collections. - Added
  filtering capabilities for ChromaCollection in GraphQL. - Introduced input types for handling
  document and collection data. - Enhanced document embedding functionality with support for
  metadata. - Added enums for message roles and tool types. - Created initial migrations for the new
  models and fields.

- Add docker dev workflow
  ([`deb776a`](https://github.com/arkitektio/alpaka-server/commit/deb776a3714ab922c7fc3547c5144bccf373957a))

- Add health check functionality and dependencies
  ([`1f54b89`](https://github.com/arkitektio/alpaka-server/commit/1f54b89742137324974f9eed79e64835ea7c8367))

- Add organization support
  ([`df7957d`](https://github.com/arkitektio/alpaka-server/commit/df7957d121b44245700766ae63b742c17cc59c2e))

- Add STATIC_TOKENS configuration to AUTHENTIKATE settings
  ([`33ee70f`](https://github.com/arkitektio/alpaka-server/commit/33ee70f8b06b2d0edbf841360c997357598c7616))

- Add ThinkingBlockType enum and integrate into types
  ([`2526251`](https://github.com/arkitektio/alpaka-server/commit/2526251b601fda34975868b2c171f86e0f6a559c))

- Breaking config changes
  ([`f47e74a`](https://github.com/arkitektio/alpaka-server/commit/f47e74a87d5e127e0b80fd7d95e8f68c5ef4175e))

- Change django stack
  ([`81b1db2`](https://github.com/arkitektio/alpaka-server/commit/81b1db2fb00a3ebf89f9e82fa055692a32b67c5e))

- Create ollama inspection
  ([`422b1ab`](https://github.com/arkitektio/alpaka-server/commit/422b1ab44c022c5383b13476151eb02024b09f8f))

- Fix scalar map
  ([`c3ef7fe`](https://github.com/arkitektio/alpaka-server/commit/c3ef7fe78399896776c04762d663118ea8aaf6ec))

- Fix some room and provider
  ([`2a3e4eb`](https://github.com/arkitektio/alpaka-server/commit/2a3e4ebd555e16ec7bf3e683e88b001a4ebaa000))

- More language features
  ([`3e227a4`](https://github.com/arkitektio/alpaka-server/commit/3e227a4490e812bc20539aaef1155c4e834122d0))

- Update authentikate dependency to version 0.14 and refactor room deletion logic
  ([`2b39d92`](https://github.com/arkitektio/alpaka-server/commit/2b39d921df9b64a6ebfc085e184b50071ca746a9))

- With filter types
  ([`2c7b5c1`](https://github.com/arkitektio/alpaka-server/commit/2c7b5c1575a9b40f601e306e7a5b4da7c1c3ebc3))

- With jwks_uri
  ([`7ee302e`](https://github.com/arkitektio/alpaka-server/commit/7ee302e69a1a52f22a8b8595cc13cd7882c6ea41))

- With new release workflow
  ([`d7d7dfb`](https://github.com/arkitektio/alpaka-server/commit/d7d7dfb535ecc06d6df8243eb41d2e88c4f271d3))
