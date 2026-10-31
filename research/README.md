# Reusable research source

See ../docs/RESEARCH.md. Install pcb-routelab first. These modules retain the original algorithms, with dependency-location and model configuration adapters. They do not include the original dataset-specific campaign runners or their private inputs. Default test/import paths do not call a provider. The provider-facing functions require the same explicit PCB_ROUTELAB_ENABLE_MODEL=1 opt-in and reject PCB_ROUTELAB_OFFLINE=1.
