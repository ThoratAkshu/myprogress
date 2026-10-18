// Runs Python in the browser with Pyodide (CPython compiled to WebAssembly), away from the page so a slow program
// can't freeze it. The first load downloads about 10 MB; the browser keeps it after that.
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
importScripts(`${PYODIDE}pyodide.js`);

const ready = (async () => {
  const pyodide = await loadPyodide({ indexURL: PYODIDE });
  const runner = await fetch(new URL(self.location.href).searchParams.get("runner"));
  pyodide.runPython(await runner.text());
  return pyodide;
})();

ready.then(() => self.postMessage({ ready: true }), error => self.postMessage({ loadFailed: String(error) }));

self.onmessage = async ({ data }) => {
  try {
    const pyodide = await ready;
    const run = pyodide.globals.get("run");
    const result = run(data.code, data.trace, data.limit, JSON.stringify(data.tests || []));
    run.destroy();
    self.postMessage({ id: data.id, ...JSON.parse(result) });
  } catch (error) {
    self.postMessage({ id: data.id, failed: String(error) });
  }
};
