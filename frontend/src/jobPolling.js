// Fetch artifacts before publishing the terminal status: publishing it can
// tear down the React effect that owns this poller.
export function startJobPolling({ fetchJob, fetchArtifact, onArtifact, onJob, onComplete, onError, interval = 2000 }) {
  let cancelled = false
  let timer
  const poll = async () => {
    try {
      const job = await fetchJob()
      if (cancelled) return
      if (job.status === 'completed') {
        const artifact = await fetchArtifact()
        if (cancelled) return
        onArtifact(artifact)
        onJob(job)
        Promise.resolve(onComplete?.()).catch(onError)
        return
      }
      onJob(job)
      if (job.status === 'failed') return
    } catch (error) {
      if (!cancelled) onError(error)
    }
    if (!cancelled) timer = setTimeout(poll, interval)
  }
  poll()
  return () => { cancelled = true; clearTimeout(timer) }
}
