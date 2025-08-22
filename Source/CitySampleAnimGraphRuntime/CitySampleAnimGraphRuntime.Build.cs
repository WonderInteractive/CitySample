// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;

public class CitySampleAnimGraphRuntime : ModuleRules
{
	public CitySampleAnimGraphRuntime(ReadOnlyTargetRules Target) : base(Target)
	{
		PrivatePCHHeaderFile = "CitySampleAnimGraphRuntime.h";
		PrivateIncludePaths.Add(ModuleDirectory);


		PublicDependencyModuleNames.AddRange(
			new string[] { 
				"Core", 
				"CoreUObject", 
				"Engine",
                "AnimationCore",
				"AnimGraphRuntime",
				"AnimGraph",
				"BlueprintGraph",
				"CitySample"
			}
		);

		PrivateDependencyModuleNames.AddRange(
			new string[] {
				"TraceLog",
			}
		);

		SetupModulePhysicsSupport(Target);
	}
}
