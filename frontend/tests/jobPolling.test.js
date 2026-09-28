import { test } from 'node:test'
import assert from 'node:assert/strict'
import { startJobPolling } from '../src/jobPolling.js'
const flush = () => new Promise((resolve) => setImmediate(resolve))

test('completion publishes artifact before status can cancel the effect', async () => {
  const events = []
  let resolveArtifact
  const artifact = new Promise((resolve) => { resolveArtifact = resolve })
  const stop = startJobPolling({
    fetchJob: async () => ({ status: 'completed' }),
    fetchArtifact: () => artifact,
    onArtifact: (data) => events.push(data),
    onJob: () => { events.push('completed'); stop() },
    onError: assert.fail,
  })
  await flush()
  assert.deepEqual(events, [])
  resolveArtifact('summary')
  await flush()
  assert.deepEqual(events, ['summary', 'completed'])
})

test('switching paper discards the previous artifact', async () => {
  let resolveArtifact
  const artifact = new Promise((resolve) => { resolveArtifact = resolve })
  const stop = startJobPolling({
    fetchJob: async () => ({ status: 'completed' }), fetchArtifact: () => artifact,
    onArtifact: assert.fail, onJob: assert.fail, onError: assert.fail,
  })
  await flush()
  stop()
  resolveArtifact('old paper')
  await flush()
})

test('failed artifact fetch can be retried before marking completed', async () => {
  let calls = 0
  let stop
  const done = new Promise((resolve) => {
    stop = startJobPolling({
      fetchJob: async () => ({ status: 'completed' }),
      fetchArtifact: async () => { if (++calls === 1) throw new Error('temporary'); return 'ok' },
      onArtifact: (value) => assert.equal(value, 'ok'), onJob: resolve,
      onError: () => {}, interval: 1,
    })
  })
  await done
  stop()
  assert.equal(calls, 2)
})
