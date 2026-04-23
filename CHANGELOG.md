# Changelog

## [0.4.0](https://github.com/lewis6991/make-ls/compare/v0.3.0...v0.4.0) (2026-04-23)


### Features

* add LSP file logging ([87d6378](https://github.com/lewis6991/make-ls/commit/87d63788d86abab0aefb827bc6c0119a50d7f211))
* add Make quick fixes and prerequisite lint ([e5e452b](https://github.com/lewis6991/make-ls/commit/e5e452b4063b06b95b98d0ba0051a7a76b50ef32))
* add make-ls check subcommand ([bf763de](https://github.com/lewis6991/make-ls/commit/bf763de0d694cb5cd070d6333c47921a5638a219))
* add more Makefile diagnostics ([1d84af2](https://github.com/lewis6991/make-ls/commit/1d84af26f90e961fb24916d630a204fc0900bbf7))
* improve check output ([1016e72](https://github.com/lewis6991/make-ls/commit/1016e721f61521bc406bde69449b14d6b3acdab3))
* track Make symbol context ([727697b](https://github.com/lewis6991/make-ls/commit/727697b46e22b60c4f9159fb28978652e69642e7))


### Bug Fixes

* improve diagnostics for includes and grouped targets ([0c3a75b](https://github.com/lewis6991/make-ls/commit/0c3a75b6386c8f20b2f5a83c1dc62adcbc469d1a))
* respect direct recipe-local eval assignments ([c92d1bc](https://github.com/lewis6991/make-ls/commit/c92d1bca8bdff6b2b732ad92485bd7ca73f1ba16))


### Documentation

* simplify README ([b7313b1](https://github.com/lewis6991/make-ls/commit/b7313b1ac3b0140802819fee63e3017cbf6d93d1))

## [0.3.0](https://github.com/lewis6991/make-ls/compare/v0.2.0...v0.3.0) (2026-04-22)


### Features

* add textDocument/references support ([0482bbd](https://github.com/lewis6991/make-ls/commit/0482bbd5efb03a33af2f9f4f12130f3f27a5c066))
* add variable rename support ([97a3154](https://github.com/lewis6991/make-ls/commit/97a31546e0e88205251540cbd4d200a4af55ddf3))
* follow explicit include directives for target lookup ([1b87ce7](https://github.com/lewis6991/make-ls/commit/1b87ce7afc783d44944c8a18fe272f3f4798ffe5))


### Performance Improvements

* avoid fallback scans for local hover ([46ed877](https://github.com/lewis6991/make-ls/commit/46ed8776af7fad6b87a0f8e264c47555c52461e9))


### Documentation

* add README badges ([4f55bef](https://github.com/lewis6991/make-ls/commit/4f55bef415da69c2b1c77579388d6633e97f93e5))

## [0.2.0](https://github.com/lewis6991/make-ls/compare/v0.1.0...v0.2.0) (2026-04-22)


### Features

* add GNU Make builtin hover support ([9a5cde7](https://github.com/lewis6991/make-ls/commit/9a5cde781b01c63c3c378226c8399e1487395858))
* add workspace target resolution ([c1f7e03](https://github.com/lewis6991/make-ls/commit/c1f7e03add44db98f38f822f77b2d6def7712cc1))
* build initial makels language server ([90883d2](https://github.com/lewis6991/make-ls/commit/90883d202996a995dfb6f055f9d6cc77fd4a05ac))
* replace tree-sitter with owned make parser ([eb05346](https://github.com/lewis6991/make-ls/commit/eb053460fc4d9e27995e0a55abf18cea5095ef5d))


### Documentation

* add MIT license and rewrite README ([30c6e9a](https://github.com/lewis6991/make-ls/commit/30c6e9a704aac03a16f3143da5fc05c73bd92894))

## Changelog

All notable changes to this project will be documented in this file.

This file is managed by release-please.
