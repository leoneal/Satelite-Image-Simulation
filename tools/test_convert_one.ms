-- Test: convert Beidou to Collada (.dae) which preserves textures better

maxPath = @"F:\钱室\卫星图像仿真\data\sat_models\models\导航卫星\导航_1_Beidou-GEO\模型\1_Beidou-GEO_model.max"
outPath = @"F:\钱室\卫星图像仿真\data\sat_models\fbx\导航卫星\导航_1_Beidou-GEO\1_Beidou-GEO_model.dae"

resetMaxFile #noPrompt
loadMaxFile maxPath quiet:true

exportFile outPath #noPrompt selectedOnly:false using:COLLADAEXP

print ("Done: " + outPath)
