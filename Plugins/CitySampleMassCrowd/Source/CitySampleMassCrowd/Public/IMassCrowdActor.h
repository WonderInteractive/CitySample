// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#if UE_ENABLE_INCLUDE_ORDER_DEPRECATED_IN_5_6
#include "CoreMinimal.h"
#include "MassCommonTypes.h"
#include "MassEntityTypes.h"
#endif // UE_ENABLE_INCLUDE_ORDER_DEPRECATED_IN_5_5
#include "UObject/Interface.h"
#include "MassEntityHandle.h"
#include "IMassCrowdActor.generated.h"


struct FMassEntityManager;

UINTERFACE(Blueprintable)
class CITYSAMPLEMASSCROWD_API UMassCrowdActorInterface : public UInterface
{
    GENERATED_BODY()
};

class IMassCrowdActorInterface
{
	GENERATED_BODY()
	
public:

	virtual void OnGetOrSpawn(FMassEntityManager* EntityManager, const FMassEntityHandle MassAgent) = 0;

	virtual void SetAdditionalMeshOffset(const float Offset) = 0;
};
