// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#if UE_ENABLE_INCLUDE_ORDER_DEPRECATED_IN_5_6
#include "CoreMinimal.h"
#endif // UE_ENABLE_INCLUDE_ORDER_DEPRECATED_IN_5_6
#include "MassSettings.h"
#include "MassCrowdAnimationSettings.generated.h"

UCLASS(config = Mass, defaultconfig, meta=(DisplayName="CitySample Mass Crowd Animation"))
class CITYSAMPLEMASSCROWD_API UMassCrowdAnimationSettings : public UMassModuleSettings
{
	GENERATED_BODY()

public:

	static const UMassCrowdAnimationSettings* Get()
	{
		return GetDefault<UMassCrowdAnimationSettings>();
	}

	UPROPERTY(EditAnywhere, config, Category = LOD);
	TArray<int32> CrowdAnimFootLODTraceFrequencyPerLOD = {5, 10, 15};

	UPROPERTY(EditAnywhere, config, Category = Anim);
	TArray<FName> CommonCrowdContextualAnimNames;

private:

	UFUNCTION()
	static TArray<FString> GetContextualAnimOptions()
	{
		TArray<FString> ContextualAnimNames;

		for (const FName& AnimName : UMassCrowdAnimationSettings::Get()->CommonCrowdContextualAnimNames)
		{
			if (AnimName != NAME_None)
			{
				ContextualAnimNames.Add(AnimName.ToString());
			}
		}

		return ContextualAnimNames;
	}
};
