// Optional development check against Khronos glTF-Validator; not runtime code.
// Install: npm install --prefix work/validators gltf-validator@2.0.0-dev.3.10
const path = require('node:path');
const fs = require('node:fs');
const filename = process.argv[2];
if (!filename) { console.error('Usage: node tools/validate_glb.cjs <model.glb>'); process.exit(2); }
const validator = require(require.resolve('gltf-validator', {paths:[process.cwd(),path.join(process.cwd(),'work/validators')]}));
validator.validateBytes(new Uint8Array(fs.readFileSync(filename)), {uri:path.basename(filename),maxIssues:50}).then(report => {
  const result = {validator:validator.version(),errors:report.issues.numErrors,warnings:report.issues.numWarnings,
    messages:report.issues.messages.map(m => ({code:m.code,message:m.message,pointer:m.pointer})).slice(0,8)};
  console.log(JSON.stringify(result));
  if (result.errors) process.exitCode=1;
}).catch(error => {console.error(String(error).slice(0,1000));process.exitCode=1;});
