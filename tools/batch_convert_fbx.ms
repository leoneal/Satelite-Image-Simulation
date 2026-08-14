/*
 * Batch .max → .fbx converter for satellite model library.
 * Usage: Open 3ds Max, go to Scripting > MAXScript Editor,
 *        open this file, press Ctrl+E to run.
 *
 * Converts all .max files under ROOT_DIR to .fbx under OUT_DIR,
 * preserving the category/satellite directory structure.
 */

ROOT_DIR  = @"F:\钱室\卫星图像仿真\data\sat_models\models"
OUT_DIR   = @"F:\钱室\卫星图像仿真\data\sat_models\fbx"

fn findAllMaxFiles root =
(
    local files = #()
    local dirs = #(root)
    while dirs.count > 0 do
    (
        local dir = dirs[1]
        deleteItem dirs 1
        local entries = getDirectories (dir + "\\*")
        for entry in entries do append dirs entry
        local maxFiles = getFiles (dir + "\\*.max")
        for mf in maxFiles do append files mf
    )
    files
)

fn ensureDir dir =
(
    makeDir dir all:true
)

fn relPath base full =
(
    local blen = base.count
    local sub = substring full (blen + 2) (full.count - blen - 1)
    -- strip extension
    local dotPos = sub.count
    for i = sub.count to 1 by -1 do
    (
        if sub[i] == "." then (dotPos = i; exit)
    )
    substring sub 1 (dotPos - 1)
)

-- Main
allFiles = findAllMaxFiles ROOT_DIR
print ("Found " + (allFiles.count as string) + " .max files")

for i = 1 to allFiles.count do
(
    local maxPath = allFiles[i]
    local rel  = relPath ROOT_DIR maxPath
    local outPath  = OUT_DIR + "\\" + rel + ".fbx"
    local outDir   = getFilenamePath outPath

    print ("[" + (i as string) + "/" + (allFiles.count as string) + "] " + \
           (getFilenameFile maxPath))

    ensureDir outDir
    resetMaxFile #noPrompt
    loadMaxFile maxPath quiet:true

    FBXExporterSetParam "EmbedTextures" true
    exportFile outPath #noPrompt selectedOnly:false using:FBXEXP

    print ("  -> " + outPath)
)

print "\n=== Done ==="
print (allFiles.count as string + " files converted")
