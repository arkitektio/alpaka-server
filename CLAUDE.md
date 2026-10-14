# alpaka

Notes for whoever changes this service, person or agent.

## Migrations and jobs

A container of this image only serves. An installer (konstruktor) prepares the database with
`arkitekt-service run migrate` once per build — before the first start, and in an update before
anything is recreated — and runs everything else as a job the image offers by name
(`konstruktor job run alpaka <job>`). Nothing is migrated, seeded or repaired at start.

**Read the rules before changing a model, a management command or `alpaka_server/contract.py`:**
<https://github.com/arkitektio/arkitekt-service/blob/main/docs/migrations-and-jobs.md>. The ones that are broken most easily:

- A model change and its migration are one commit.
- Within a major, a migration leaves a schema the previous release still runs on: a failed
  update, and a rollback, start the old build on the migrated database. What cannot do that
  is a `feat!:`.
- A `manage.py` command an operator should be able to run on a hub is declared in `jobs=` in
  `alpaka_server/contract.py`; one nobody runs is deleted. Any job is safe to run again.
- What `setup=` names runs for every build, after the migrations: it changes nothing the
  second time and needs nothing but the database and the config.
- Existing data is rewritten by a data migration when that needs only the database (it runs
  once, with the service stopped), and by a re-runnable job in `setup=` when it needs the
  service's code or its storage. There is no upgrade step, and nothing is keyed to a version.

What this service declares:

- Setup, in order: `ensureadmin`, `ensurepartners`, `restore_descriptors`. The third stores the
  descriptors of every room, message, model, collection and provider that misses a declared key
  (rows from before a key existed); `--all` describes every row again after a describer changed
  what a key means.
- Other jobs: `inspectollama`.

`tests/test_prepared.py` holds the contract to this: migrations committed, every job a command
of this service, the setup run twice. In `deployments/next` the service runs
`arkitekt-service standalone --debug`, which migrates and then serves: restart its container
to apply a new migration.

## Descriptors

Every descriptor is stored (`stored_descriptors`, recomputed on every save by
`arkitekt_service`), so a port's `requires` is the `requires` argument of a list filter, one
indexed query. The describers are in `alpaka_server/descriptors.py`; a provider describes only
its kind, never anything secret. What a save of the row cannot see is restored in
`alpaka_server/service.py`: attaching or detaching structures (`m2m_changed`), an agent joining
or leaving a room (`@alpaka/n_agents`), a provider saved under its models
(`@alpaka/provider_kind`). A mutation that writes a row and then what describes it is one
transaction (`send`, `createRoom`), so its CREATED carries both; `finishMessage` attaches before
it closes the message, so its one UPDATED does. A bulk write (`update()`, `bulk_update`) of a
field a descriptor reads restores the rows (`service.restore`); appending streamed text is one,
and no descriptor reads text.
