"""Generate the dependency-free Xcode project deterministically."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = '''// !$*UTF8*$!
{
 archiveVersion = 1;
 classes = {};
 objectVersion = 56;
 objects = {
 A10000000000000000000001 = {isa = PBXProject; attributes = {LastUpgradeCheck = 1640;}; buildConfigurationList = A10000000000000000000002; compatibilityVersion = "Xcode 14.0"; developmentRegion = en; hasScannedForEncodings = 0; knownRegions = (en, Base); mainGroup = A10000000000000000000003; productRefGroup = A10000000000000000000004; projectDirPath = ""; projectRoot = ""; targets = (A10000000000000000000005);};
 A10000000000000000000002 = {isa = XCConfigurationList; buildConfigurations = (A10000000000000000000010, A10000000000000000000011); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release;};
 A10000000000000000000003 = {isa = PBXGroup; children = (A10000000000000000000006, A10000000000000000000007, A10000000000000000000004, A1000000000000000000001D, A10000000000000000000019, A1000000000000000000001A); sourceTree = "<group>";};
 A10000000000000000000004 = {isa = PBXGroup; children = (A10000000000000000000008); name = Products; sourceTree = "<group>";};
 A10000000000000000000005 = {isa = PBXNativeTarget; buildConfigurationList = A10000000000000000000009; buildPhases = (A10000000000000000000012, A10000000000000000000013, A10000000000000000000014); buildRules = (); dependencies = (); name = Ledger; productName = Ledger; productReference = A10000000000000000000008; productType = "com.apple.product-type.application";};
 A10000000000000000000006 = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = LedgerApp/LedgerApp.swift; sourceTree = "<group>";};
 A10000000000000000000007 = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = LedgerCore/Sources/LedgerCore/Ledger.swift; sourceTree = "<group>";};
 A10000000000000000000008 = {isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = Ledger.app; sourceTree = BUILT_PRODUCTS_DIR;};
 A10000000000000000000009 = {isa = XCConfigurationList; buildConfigurations = (A10000000000000000000015, A10000000000000000000016); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release;};
 A10000000000000000000010 = {isa = XCBuildConfiguration; buildSettings = {SDKROOT = iphoneos; IPHONEOS_DEPLOYMENT_TARGET = 17.0; CLANG_ENABLE_MODULES = YES; SWIFT_VERSION = 6.0;}; name = Debug;};
 A10000000000000000000011 = {isa = XCBuildConfiguration; buildSettings = {SDKROOT = iphoneos; IPHONEOS_DEPLOYMENT_TARGET = 17.0; CLANG_ENABLE_MODULES = YES; SWIFT_VERSION = 6.0;}; name = Release;};
 A10000000000000000000012 = {isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (A10000000000000000000017, A10000000000000000000018); runOnlyForDeploymentPostprocessing = 0;};
 A10000000000000000000013 = {isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0;};
 A10000000000000000000014 = {isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = (A1000000000000000000001B,A1000000000000000000001C); runOnlyForDeploymentPostprocessing = 0;};
 A10000000000000000000015 = {isa = XCBuildConfiguration; baseConfigurationReference = A1000000000000000000001D; buildSettings = {GENERATE_INFOPLIST_FILE = YES; ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon; INFOPLIST_KEY_CFBundleDisplayName = Minto; INFOPLIST_KEY_UILaunchStoryboardName = LaunchScreen; INFOPLIST_FILE = LedgerApp/Info.plist; INFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES;  INFOPLIST_KEY_UISupportedInterfaceOrientations = "UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight"; PRODUCT_BUNDLE_IDENTIFIER = com.ashwin.splitwiseledger; PRODUCT_NAME = "$(TARGET_NAME)"; TARGETED_DEVICE_FAMILY = "1,2"; SWIFT_VERSION = 6.0; MARKETING_VERSION = 0.1; CURRENT_PROJECT_VERSION = 1; CODE_SIGN_STYLE = Automatic; SWIFT_ACTIVE_COMPILATION_CONDITIONS = "DEBUG $(inherited)"; SWIFT_OPTIMIZATION_LEVEL = "-Onone"; DEBUG_INFORMATION_FORMAT = dwarf;}; name = Debug;};
 A10000000000000000000016 = {isa = XCBuildConfiguration; buildSettings = {GENERATE_INFOPLIST_FILE = YES; ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon; INFOPLIST_KEY_CFBundleDisplayName = Minto; INFOPLIST_KEY_UILaunchStoryboardName = LaunchScreen; INFOPLIST_FILE = LedgerApp/Info.plist; INFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES;  INFOPLIST_KEY_UISupportedInterfaceOrientations = "UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight"; PRODUCT_BUNDLE_IDENTIFIER = com.ashwin.splitwiseledger; PRODUCT_NAME = "$(TARGET_NAME)"; TARGETED_DEVICE_FAMILY = "1,2"; SWIFT_VERSION = 6.0; MARKETING_VERSION = 0.1; CURRENT_PROJECT_VERSION = 1; CODE_SIGN_STYLE = Automatic; SWIFT_OPTIMIZATION_LEVEL = "-O"; DEBUG_INFORMATION_FORMAT = "dwarf-with-dsym";}; name = Release;};
 A10000000000000000000017 = {isa = PBXBuildFile; fileRef = A10000000000000000000006;};
 A10000000000000000000018 = {isa = PBXBuildFile; fileRef = A10000000000000000000007;};

 A10000000000000000000019 = {isa = PBXFileReference; lastKnownFileType = folder.assetcatalog; path = LedgerApp/Assets.xcassets; sourceTree = "<group>";};
 A1000000000000000000001A = {isa = PBXFileReference; lastKnownFileType = file.storyboard; path = LedgerApp/LaunchScreen.storyboard; sourceTree = "<group>";};
 A1000000000000000000001B = {isa = PBXBuildFile; fileRef = A10000000000000000000019;};
 A1000000000000000000001C = {isa = PBXBuildFile; fileRef = A1000000000000000000001A;};
 A1000000000000000000001D = {isa = PBXFileReference; lastKnownFileType = text.xcconfig; path = Configuration.xcconfig; sourceTree = "<group>";};
 };
 rootObject = A10000000000000000000001;
}
'''
(root / 'LedgerApp.xcodeproj' / 'project.pbxproj').write_text(project)
scheme_dir = root / 'LedgerApp.xcodeproj' / 'xcshareddata' / 'xcschemes'
scheme_dir.mkdir(parents=True, exist_ok=True)
(scheme_dir / 'Ledger.xcscheme').write_text('''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1640" version="1.3">
<BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES"><BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="A10000000000000000000005" BuildableName="Ledger.app" BlueprintName="Ledger" ReferencedContainer="container:LedgerApp.xcodeproj"/></BuildActionEntry></BuildActionEntries></BuildAction>
<LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" debugServiceExtension="internal" allowLocationSimulation="YES"><BuildableProductRunnable runnableDebuggingMode="0"><BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="A10000000000000000000005" BuildableName="Ledger.app" BlueprintName="Ledger" ReferencedContainer="container:LedgerApp.xcodeproj"/></BuildableProductRunnable></LaunchAction>
<AnalyzeAction buildConfiguration="Debug"/><ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>
''')
