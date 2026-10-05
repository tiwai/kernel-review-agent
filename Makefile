# Makefile for kernel-review-agent

PREFIX ?= /usr/local
BINDIR = $(PREFIX)/bin
DATADIR = $(PREFIX)/share/kernel-review-agent
DOCDIR = $(PREFIX)/share/doc/kernel-review-agent
PYTHON ?= python3

# Prompt sets: each subdirectory of prompts/ (e.g. default, small)
PROMPT_SETS = $(notdir $(patsubst %/,%,$(wildcard prompts/*/)))

# Installation directories
INSTALL = install
INSTALL_PROGRAM = $(INSTALL) -m 755
INSTALL_DATA = $(INSTALL) -m 644
INSTALL_DIR = $(INSTALL) -d

.PHONY: all install install-bin install-data install-prompts install-docs uninstall clean test

all:
	@echo "Run 'make install' to install kernel-review-agent"
	@echo "Run 'make install PREFIX=/usr' for system-wide installation"
	@echo "Run 'make install PREFIX=~/.local' for user installation"

# Install everything
install: install-bin install-data install-prompts install-docs
	@echo ""
	@echo "Installation complete!"
	@echo "  Binary: $(BINDIR)/kernel-review-agent"
	@echo "  Prompts: $(DATADIR)/prompts/"
	@echo "  Docs: $(DOCDIR)/"
	@echo ""
	@echo "Add $(BINDIR) to your PATH if needed:"
	@echo "  export PATH=\"$(BINDIR):\$$PATH\""

# Install main script
install-bin:
	$(INSTALL_DIR) $(DESTDIR)$(BINDIR)
	$(INSTALL_PROGRAM) kernel_review_agent.py $(DESTDIR)$(BINDIR)/kernel-review-agent

# Install Python modules
install-data:
	$(INSTALL_DIR) $(DESTDIR)$(DATADIR)
	$(INSTALL_DATA) config.py $(DESTDIR)$(DATADIR)/
	# Install Python modules
	$(INSTALL_DIR) $(DESTDIR)$(DATADIR)/analysis
	$(INSTALL_DATA) analysis/*.py $(DESTDIR)$(DATADIR)/analysis/
	$(INSTALL_DIR) $(DESTDIR)$(DATADIR)/git_integration
	$(INSTALL_DATA) git_integration/*.py $(DESTDIR)$(DATADIR)/git_integration/
	$(INSTALL_DIR) $(DESTDIR)$(DATADIR)/llm_integration
	$(INSTALL_DATA) llm_integration/*.py $(DESTDIR)$(DATADIR)/llm_integration/
	$(INSTALL_DIR) $(DESTDIR)$(DATADIR)/output
	$(INSTALL_DATA) output/*.py $(DESTDIR)$(DATADIR)/output/
	$(INSTALL_DIR) $(DESTDIR)$(DATADIR)/prompt_management
	$(INSTALL_DATA) prompt_management/*.py $(DESTDIR)$(DATADIR)/prompt_management/

# Install prompts
install-prompts:
	$(INSTALL_DIR) $(DESTDIR)$(DATADIR)/prompts
	$(INSTALL_DATA) prompts/prompt-sets.json prompts/*.md $(DESTDIR)$(DATADIR)/prompts/
	# Install each prompt set (prompts/<set>/ and prompts/<set>/subsystem/)
	for set in $(PROMPT_SETS); do \
		$(INSTALL_DIR) $(DESTDIR)$(DATADIR)/prompts/$$set/subsystem && \
		$(INSTALL_DATA) prompts/$$set/*.md $(DESTDIR)$(DATADIR)/prompts/$$set/ && \
		$(INSTALL_DATA) prompts/$$set/subsystem/*.md $(DESTDIR)$(DATADIR)/prompts/$$set/subsystem/ || exit 1; \
	done

# Install documentation
install-docs:
	$(INSTALL_DIR) $(DESTDIR)$(DOCDIR)
	$(INSTALL_DATA) README.md $(DESTDIR)$(DOCDIR)/
	$(INSTALL_DATA) QUICKSTART.md $(DESTDIR)$(DOCDIR)/
	$(INSTALL_DATA) docs/dev/DEBUG_GUIDE.md $(DESTDIR)$(DOCDIR)/
	$(INSTALL_DATA) docs/dev/LLM_PROVIDERS.md $(DESTDIR)$(DOCDIR)/
	$(INSTALL_DATA) docs/dev/CONFIGURATION.md $(DESTDIR)$(DOCDIR)/
	$(INSTALL_DATA) LICENSE $(DESTDIR)$(DOCDIR)/
	$(INSTALL_DATA) LICENSE-PROMPTS $(DESTDIR)$(DOCDIR)/
	$(INSTALL_DATA) config.json.example $(DESTDIR)$(DOCDIR)/

# Uninstall
uninstall:
	rm -f $(DESTDIR)$(BINDIR)/kernel-review-agent
	rm -rf $(DESTDIR)$(DATADIR)
	rm -rf $(DESTDIR)$(DOCDIR)
	@echo "Uninstalled kernel-review-agent from $(PREFIX)"

# Clean build artifacts
clean:
	rm -rf build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	find . -type f -name '*.pyo' -delete

# Run tests
test:
	$(PYTHON) -m pytest -v || echo "Tests not yet implemented"

# Development: install in editable mode
dev-install:
	pip install -e .
