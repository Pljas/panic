Change the contents of this file to this:

# Change Log

## 0.3.0

Released on 9th December 2021

- Updated the Web-Installer to cater for GETH RPC Monitoring
- Added EVM node store, Chainlink contract store and tests for both.
- Added EVM Node Monitoring along with the monitor tests.
- Added ChainlinkContractsMonitor along with its tests.
- Added ContractMonitorsManager along with its tests.
- Added EVM Node Data Transformer along with its tests.
- Added ChainlinkContractsDataTransformer along with its tests.
- Added EVMNodeAlerterManager and its tests.
- Added the ChainlinkAlertersManager and its tests.
- Added EVMNodeAlerter and its tests.
- Added ChainlinkNodeAlerter and its tests.
- Added ChainlinkContractAlerter and its tests.
- Removed `no_of_active_jobs` as `job_subscriber_subscriptions` is no longer found
- Added QOL improvements: mid-form popup warnings, custom weiwatcher network input, other changes such as descriptions etc.

## 0.2.0 (Part of 0.3.0 tag)

Released on 9th December 2021

- Fixed tests to work with alerter changes. Merged multiple tests into one using parameterization.
- Updated Alerter to fix bugs with regards to metric changes in thresholds.
- Added Internal Alerts on startup originating from the Alerter, which are used to reset all metrics for that chain.
- Added functionality to cater for new Internal Alert in Data Store.
- Added Tests for new Internal Alerts in System/Github Alerter and Alert Store.
- Added the ChainlinkNodeMonitor, ChainlinkNodeDataTransformer, DataTransformersManager chainlink logic, NodeMonitorsManager, and their tests.
- Refactored RabbitMQ queues and routing keys.
- The SystemMonitorsManager additionally now parses systems belonging to chains from the `system_config.ini` if Chainlink is the base chain. Same schema as `GENERAL` is expected.
- Web-Installer visually updated to look better
- Web-Installer Chainlink/DockerHub/Slack have been integrated for the setup process
- Fixed issue with Internal Alerts generation when the Alert Router is not yet up.
- Fixed issue with GitHub alerter raising new release alerts in reverse order for multiple releases.
- The data store components are now compatible with the base Chainlink integration features.
- Added Chainlink Node Alerter Manager and tests.
- Web-Installer bug fixes and removing outdated alerts.
- Added Chainlink Node Alerter logic and tests.
- Integrated Slack as an alerting channel and command handler.
- Added new components heartbeat to Slack.

## 0.1.2

Released on 25th March 2021

- Fixed bug in the web-installer where the BLACKLIST wasn't being exported properly

## 0.1.1

Released on 24th March 2021

- Fixed bug where the `metric_not_found` key was missing inside the store keys.
- Fixed tests having issues running in docker and pipenv.

## 0.1.0

Released on 22nd March 2021

This version contains the following:
* A base alerter that can alert about the host system the nodes are running by monitoring system metrics exposed by node exporter
* A base alerter that can alert on new releases for any GitHub repository.
* Multiple alerting channels supported, namely PagerDuty, OpsGenie, Telegram, E-mail and Twilio.
* A web-based installer to easily set-up PANIC
* A dockerized set-up for easy installation and communication between the different components.