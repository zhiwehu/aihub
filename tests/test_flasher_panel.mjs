import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

// The USB onboarding panel is markup in this page, but the module that binds to
// it ships with aihub-firmware (flash/echoear-installer.js) and does its lookups
// at module load. A missing id is a TypeError in the browser before any panel is
// drawn, so the contract is pinned here. Keep this list in sync with that module.
const REQUIRED = `echoear-backup echoear-connect echoear-copy-setup echoear-device-info
echoear-disconnect echoear-heard echoear-install-progress echoear-install-status
echoear-installer echoear-network-choice echoear-network-form echoear-network-host
echoear-network-intro echoear-open-network echoear-release-status echoear-restore
echoear-serial-note echoear-setup echoear-setup-status echoear-technical-details
echoear-update-note echoear-update-with-setup echoear-upgrade echoear-verify-status
echoear-wifi-fields echoear-wifi-hint echoear-wifi-mode echoear-wifi-open
echoear-wifi-password echoear-wifi-ssid`.split(/\s+/);

const html = await readFile(new URL('../public/index.html',import.meta.url),'utf8');
const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map(match => match[1]));

test('every id the USB onboarding module binds exists in the page', () => {
  assert.deepEqual(REQUIRED.filter(id => !ids.has(id)),[]);
});

test('the flashing panel stays hidden until a client selects it', () => {
  assert.match(html,/<article id="echoear-installer"[^>]*hidden/);
});

test('the console loads the module from the firmware mount instead of vendoring it', async () => {
  const source = await readFile(new URL('../public/connections.js',import.meta.url),'utf8');
  assert.match(source,/import\('\/firmware\/echoear-installer\.js'\)/);
  assert.match(source,/window\.AIHubFlasher/);
});
